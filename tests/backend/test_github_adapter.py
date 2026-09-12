"""Exercise the real GitHub adapter without network or real side effects."""

import json
from dataclasses import replace

import pytest

from chatty.integrations.github import reads, writes
from chatty.integrations.gpt_live.executor import (
    ExecutorError,
    ToolExecutor,
    ToolRegistry,
)


@pytest.fixture
def github_executor(settings, tmp_path, monkeypatch):
    calls = []

    def create_issue(title, body):
        calls.append((title, body))
        return {
            "number": 123,
            "url": "https://github.com/vaishnavJa/Chatty/issues/123",
        }

    monkeypatch.setattr(writes, "create_issue", create_issue)
    settings = replace(settings, ledger_path=tmp_path / "private" / "ledger.sqlite3")
    executor = ToolExecutor(settings)
    executor.register("real-session", ToolRegistry.from_module())
    return executor, calls


def run_issue(executor, *, call_id="real-call", approved=False, **arguments):
    payload = {"title": "Review this exact issue", "body": "Expected issue contents."}
    payload.update(arguments)
    return executor.execute(
        "real-session", call_id, "create_issue", payload, approved=approved
    )


def test_real_adapter_requires_approval_then_accepts_same_bound_call(github_executor):
    executor, calls = github_executor
    denied = run_issue(executor)
    assert json.loads(denied["output"])["error"]["code"] == "authorization_required"
    assert calls == []
    assert not executor.settings.ledger_path.exists()

    approved = run_issue(executor, approved=True)
    assert set(approved) == {"call_id", "output"}
    output = json.loads(approved["output"])
    assert output["ok"] is True
    assert output["repository"] == "vaishnavJa/Chatty"
    assert output["data"]["number"] == 123
    assert executor.settings.ledger_path.is_file()
    assert run_issue(executor, approved=True) == approved
    assert len(calls) == 1


def test_pending_approval_cannot_change_title_body_or_tool(github_executor):
    executor, calls = github_executor
    run_issue(executor)
    for changes in ({"title": "Different"}, {"body": "Different"}):
        with pytest.raises(ExecutorError) as caught:
            run_issue(executor, approved=True, **changes)
        assert caught.value.code == "call_conflict"
    with pytest.raises(ExecutorError) as caught:
        executor.execute("real-session", "real-call", "list_open_issues", {})
    assert caught.value.code == "call_conflict"
    assert calls == []


def test_model_argument_cannot_authorize_write(github_executor):
    executor, calls = github_executor
    for field in ("approved", "explicit_user_request"):
        with pytest.raises(ExecutorError) as caught:
            executor.execute(
                "real-session",
                field,
                "create_issue",
                {"title": "Issue", "body": "Text", field: True},
            )
        assert caught.value.code == "invalid_arguments"
    assert calls == []


@pytest.mark.parametrize("value", [1, 0, "true", None, [], {}])
def test_approval_is_strict_boolean(github_executor, value):
    executor, calls = github_executor
    with pytest.raises(ExecutorError) as caught:
        run_issue(executor, approved=value)
    assert caught.value.code == "invalid_approval"
    assert calls == []


def test_real_read_needs_no_approval_and_is_not_double_wrapped(
    github_executor, monkeypatch
):
    executor, writes_seen = github_executor
    read_calls = []

    def list_recent_commits(*, limit):
        read_calls.append(limit)
        return [
            {"sha": "abc", "url": "https://github.com/vaishnavJa/Chatty/commit/abc"}
        ]

    monkeypatch.setattr(reads, "list_recent_commits", list_recent_commits)
    receipt = executor.execute(
        "real-session", "read-call", "list_recent_commits", {"limit": 2}
    )
    result = json.loads(receipt["output"])
    assert result["ok"] is True
    assert result["data"][0]["sha"] == "abc"
    assert read_calls == [2]
    assert writes_seen == []


def test_durable_adapter_prevents_duplicate_after_executor_reconstruction(
    github_executor,
):
    executor, calls = github_executor
    first = run_issue(executor, approved=True)
    resumed = ToolExecutor(executor.settings)
    resumed.register("real-session", ToolRegistry.from_module())
    assert run_issue(resumed, approved=True) == first
    assert len(calls) == 1


def test_uncertain_write_stays_uncertain_after_executor_reconstruction(
    github_executor, monkeypatch
):
    executor, _ = github_executor
    calls = []

    def uncertain_write(*args):
        calls.append(args)
        raise TimeoutError("Private upstream details must not reach the browser")

    monkeypatch.setattr(writes, "create_issue", uncertain_write)
    first = run_issue(executor, approved=True)
    assert json.loads(first["output"])["error"]["uncertain"] is True
    assert "Private upstream" not in first["output"]
    resumed = ToolExecutor(executor.settings)
    resumed.register("real-session", ToolRegistry.from_module())
    assert run_issue(resumed, approved=True) == first
    assert len(calls) == 1


def test_unapproved_expired_call_does_not_pin_session_capacity(settings):
    now = [0]
    executor = ToolExecutor(
        replace(settings, session_ttl_seconds=10, max_sessions=1),
        clock=lambda: now[0],
    )
    executor.register("real-session", ToolRegistry.from_module())
    run_issue(executor)
    now[0] = 11
    executor.ensure_capacity()
    assert executor.sessions == {}
