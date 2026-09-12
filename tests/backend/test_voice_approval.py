import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from chatty.agents.tools import WRITE_TOOL_NAMES
from chatty.integrations.gpt_live.executor import (
    ExecutorError,
    ToolExecutor,
    ToolRegistry,
)
from chatty.voice_approval import VoiceApprovals, confirmation_prompt


def event(text, *, role="input", event_id="input-1", start=2100, end=2400):
    return {
        "type": f"session.{role}_transcript.delta",
        "event_id": event_id,
        "delta": text,
        "start_ms": start,
        "end_ms": end,
    }


@pytest.fixture
def flow(settings, schemas):
    calls, clock = [], [0]
    executor = ToolExecutor(settings)
    executor.register(
        "s", ToolRegistry(schemas, lambda *args: calls.append(args) or {"ok": True})
    )
    manager = VoiceApprovals(executor, clock=lambda: clock[0], wall_clock=lambda: 1000)
    return manager, calls, clock


def prepared(manager, *, call="c", name="create_issue", arguments=None):
    return manager.prepare("s", call, name, arguments or {"title": "Fix demo"})


def armed(manager, proposal=None, *, start=1000, end=2000, event_id="output-1"):
    proposal = proposal or prepared(manager)
    assert manager.arm(
        "s",
        proposal["approval_id"],
        [
            event(
                proposal["prompt"],
                role="output",
                event_id=event_id,
                start=start,
                end=end,
            )
        ],
        True,
    ) == {"armed": True}
    return proposal


def speak(manager, proposal, text="yes", **kwargs):
    return manager.voice(
        "s", proposal["approval_id"], [event(text, **kwargs)], True, 1000
    )


def test_exact_pending_action_and_duplicate_confirmation(flow):
    manager, calls, _ = flow
    proposal = prepared(manager)
    assert proposal["expires_at"] == 1_090_000
    assert proposal == prepared(manager)
    assert not calls
    armed(manager, proposal)
    result = speak(manager, proposal, "Chatty, yes please.")
    assert result["status"] == "approved"
    assert json.loads(result["receipt"]["output"])["ok"] is True
    assert speak(manager, proposal) == result
    assert calls == [("create_issue", {"title": "Fix demo"})]


@pytest.mark.parametrize(
    "text", ["yes", "yes please", "yes do it", "confirm", "Chatty, confirm", "go ahead"]
)
def test_whole_spoken_confirmations(flow, text):
    manager, calls, _ = flow
    assert speak(manager, armed(manager), text)["status"] == "approved"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "text,status",
    [
        ("no", "rejected"),
        ("Chatty, stop", "rejected"),
        ("cancel", "rejected"),
        ("yes but change the title", "ambiguous"),
        ("someone said yes", "ambiguous"),
        ("do not approve", "ambiguous"),
    ],
)
def test_rejection_amendments_and_quoted_approval_never_execute(flow, text, status):
    manager, calls, _ = flow
    proposal = armed(manager)
    result = speak(manager, proposal, text)
    assert result["status"] == status
    assert result["receipt"]["call_id"] == "c"
    assert speak(manager, proposal)["status"] == status
    assert not calls


def test_approval_needs_finished_prompt_and_actual_input_end(flow):
    manager, calls, _ = flow
    proposal = prepared(manager)
    with pytest.raises(ExecutorError, match="finished asking"):
        speak(manager, proposal)
    with pytest.raises(ExecutorError, match="actual confirmation"):
        manager.arm("s", proposal["approval_id"], [], False)
    with pytest.raises(ExecutorError, match="complete proposed change"):
        manager.arm(
            "s",
            proposal["approval_id"],
            [event("Do you approve this change?", role="output")],
            True,
        )
    armed(manager, proposal)
    for finished, quiet in [
        (False, 1000),
        (True, 999),
        (True, True),
        (True, float("nan")),
    ]:
        with pytest.raises(ExecutorError, match="input audio"):
            manager.voice("s", proposal["approval_id"], [event("yes")], finished, quiet)
    assert not calls


@pytest.mark.parametrize(
    "events",
    [
        [event("yes", role="output")],
        [event("yes", start=1, end=10)],
        [event("yes", event_id="output-1")],
        [event("yes", start=float("nan"))],
        [event("yes", start=2600), event(" please", event_id="2", start=2500)],
    ],
)
def test_wrong_source_replays_old_timeline_and_invalid_events(flow, events):
    manager, calls, _ = flow
    proposal = armed(manager)
    with pytest.raises(ExecutorError):
        manager.voice("s", proposal["approval_id"], events, True, 1000)
    assert not calls


def test_partial_yes_followed_by_amendment(flow):
    manager, calls, _ = flow
    proposal = armed(manager)
    fragments = [
        event("yes", end=2200),
        event(" but not that title", event_id="input-2", start=2250, end=2600),
    ]
    result = manager.voice("s", proposal["approval_id"], fragments, True, 1000)
    assert result["status"] == "ambiguous"
    assert not calls


def test_expiry_and_cancel_invalidate_old_token(flow):
    manager, calls, clock = flow
    proposal = armed(manager)
    clock[0] = 91
    assert speak(manager, proposal)["status"] == "expired"
    next_proposal = prepared(manager, call="next")
    result = manager.cancel("s", next_proposal["approval_id"])
    assert result["status"] == "rejected"
    assert speak(manager, next_proposal) == result
    assert not calls


def test_changed_payload_cancels_old_and_requires_new_call(flow):
    manager, calls, _ = flow
    proposal = armed(manager)
    with pytest.raises(ExecutorError) as error:
        prepared(manager, arguments={"title": "Changed"})
    assert error.value.code == "call_conflict"
    assert speak(manager, proposal)["status"] == "rejected"
    with pytest.raises(ExecutorError):
        prepared(manager)
    assert not calls


def test_only_one_pending_and_scoped_session(flow):
    manager, calls, _ = flow
    proposal = prepared(manager)
    with pytest.raises(ExecutorError) as error:
        prepared(manager, call="other")
    assert error.value.code == "approval_pending"
    with pytest.raises(ExecutorError):
        manager.cancel("different-session", proposal["approval_id"])
    manager.cancel("s")
    prepared(manager, call="other")
    assert not calls


def test_cross_action_input_event_replay_is_rejected(flow):
    manager, calls, _ = flow
    first = armed(manager)
    speak(manager, first, "no")
    second = armed(
        manager,
        prepared(manager, call="next"),
        start=3000,
        end=4000,
        event_id="output-2",
    )
    with pytest.raises(ExecutorError):
        speak(manager, second, start=4100, end=4400)  # Reused event ID.
    assert not calls


def test_duplicate_concurrent_confirmation_and_stop_during_write(flow):
    manager, calls, _ = flow
    started, release = threading.Event(), threading.Event()

    def runner(*args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    manager.executor.sessions["s"].tools.execute_tool = runner
    proposal = armed(manager)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(speak, manager, proposal)
        assert started.wait(1)
        duplicate = pool.submit(speak, manager, proposal)
        assert manager.cancel("s")["status"] == "approved"
        release.set()
        assert duplicate.result() == first.result()
    assert len(calls) == 1


def test_uncertain_failure_never_reexecutes(flow):
    manager, calls, _ = flow

    def fail(*args):
        calls.append(args)
        raise TimeoutError("private exception")

    manager.executor.sessions["s"].tools.execute_tool = fail
    proposal = armed(manager)
    result = speak(manager, proposal)
    assert json.loads(result["receipt"]["output"])["error"]["uncertain"] is True
    assert speak(manager, proposal) == result
    assert len(calls) == 1


@pytest.mark.parametrize("name", sorted(WRITE_TOOL_NAMES))
def test_every_mutation_uses_saved_voice_approval(settings, schemas, name):
    calls = []
    executor = ToolExecutor(settings)
    executor.register(
        "s",
        ToolRegistry(
            [{**schemas[0], "name": name}],
            lambda *args: calls.append(args) or {"ok": True},
        ),
    )
    manager = VoiceApprovals(executor)
    proposal = prepared(manager, name=name)
    armed(manager, proposal)
    assert speak(manager, proposal)["status"] == "approved"
    assert calls == [(name, {"title": "Fix demo"})]


def test_prompt_announces_long_fields_and_omits_full_sha():
    prompt = confirmation_prompt(
        "update_repository_file",
        {
            "path": "demo.py",
            "branch": "demo",
            "content": "x" * 2000,
            "message": "Fix demo",
            "expected_sha": "a" * 40,
        },
        "vaishnavJa/Chatty",
    )
    assert "2000 character draft" in prompt
    assert "a" * 40 not in prompt
    assert prompt.endswith("Do you approve this change?")
    assert len(prompt) <= 650


def test_prompt_numeric_speech_and_punctuation(flow):
    manager, _, _ = flow
    proposal = prepared(manager, arguments={"title": "Fix issue 17"})
    spoken = proposal["prompt"].replace("17", "seventeen").replace(":", "").upper()
    assert manager.arm(
        "s",
        proposal["approval_id"],
        [event(spoken, role="output", start=1000, end=2000)],
        True,
    ) == {"armed": True}


@pytest.mark.parametrize("name", sorted(WRITE_TOOL_NAMES))
def test_boolean_http_bypass_fails_for_every_mutation(server_fixture, schemas, name):
    calls = []
    registry = ToolRegistry(
        [{**schemas[0], "name": name}], lambda *args: calls.append(args) or {"ok": True}
    )
    _, client, _, _ = server_fixture(tools=registry)
    session = client.post("/api/live/session", json={"sdp": "offer"}).json()["session"][
        "id"
    ]
    response = client.post(
        "/api/tools/execute",
        json={
            "session_id": session,
            "call_id": "c",
            "name": name,
            "arguments": {"title": "Proposed"},
            "approved": True,
        },
    )
    assert response.status_code == 200
    assert (
        json.loads(response.json()["output"])["error"]["code"]
        == "authorization_required"
    )
    assert not calls


@pytest.mark.parametrize("action", ["prepare", "arm", "voice", "cancel"])
def test_approval_endpoints_preserve_local_origin_boundary(server_fixture, action):
    _, client, _, calls = server_fixture()
    response = client.post(
        f"/api/approvals/{action}", json={}, headers={"Origin": "https://other.example"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "invalid_origin"
    assert not calls


def test_voice_endpoint_cannot_supply_new_payload(server_fixture):
    _, client, _, calls = server_fixture()
    session = client.post("/api/live/session", json={"sdp": "offer"}).json()["session"][
        "id"
    ]
    response = client.post(
        "/api/approvals/voice",
        json={
            "session_id": session,
            "approval_id": "x",
            "input_events": [],
            "speech_finished": True,
            "quiet_ms": 1000,
            "arguments": {"title": "Changed"},
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert not calls
