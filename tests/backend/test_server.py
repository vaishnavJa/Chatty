import json
from dataclasses import replace

import pytest

from chatty.integrations.gpt_live.client import LiveClient
from chatty.integrations.gpt_live.executor import ToolRegistry


def make_call(client, **changes):
    session = client.post("/api/live/session", json={"sdp": "v=0\r\noffer\r\n"})
    assert session.status_code == 201
    body = {
        "session_id": session.json()["session"]["id"],
        "call_id": "call-1",
        "name": "create_issue",
        "arguments": {"title": "Example bug"},
        "approved": True,
    }
    body.update(changes)
    return body


def approve_call(client, body):
    proposal = client.post(
        "/api/approvals/prepare",
        json={key: value for key, value in body.items() if key != "approved"},
    )
    assert proposal.status_code == 200, proposal.text
    token = {
        "session_id": body["session_id"],
        "approval_id": proposal.json()["approval_id"],
    }
    armed = client.post(
        "/api/approvals/arm",
        json={
            **token,
            "playback_finished": True,
            "output_events": [
                {
                    "type": "session.output_transcript.delta",
                    "event_id": "output-1",
                    "delta": proposal.json()["prompt"],
                    "start_ms": 1000,
                    "end_ms": 2000,
                }
            ],
        },
    )
    assert armed.status_code == 200, armed.text
    voice = {
        **token,
        "speech_finished": True,
        "quiet_ms": 1000,
        "input_events": [
            {
                "type": "session.input_transcript.delta",
                "event_id": "input-1",
                "delta": "Yes please.",
                "start_ms": 2200,
                "end_ms": 2400,
            }
        ],
    }
    return client.post("/api/approvals/voice", json=voice), voice


def test_complete_http_handoff_and_duplicate_receipts(server_fixture):
    _, client, live, calls = server_fixture()
    body = make_call(client)
    first, voice = approve_call(client, body)
    again = client.post("/api/approvals/voice", json=voice)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert first.json()["status"] == "approved"
    receipt = first.json()["receipt"]
    assert set(receipt) == {"call_id", "output"}
    assert isinstance(receipt["output"], str)
    assert json.loads(receipt["output"])["number"] == 42
    assert len(calls) == 1
    assert live.requests[0][0] == "v=0\r\noffer\r\n"


def test_http_boolean_cannot_replace_spoken_approval(server_fixture):
    _, client, _, calls = server_fixture()
    body = make_call(client)
    del body["approved"]
    denied = client.post("/api/tools/execute", json=body)
    assert denied.status_code == 200
    assert (
        json.loads(denied.json()["output"])["error"]["code"] == "authorization_required"
    )
    assert calls == []
    body["approved"] = True
    bypass = client.post("/api/tools/execute", json=body)
    assert (
        json.loads(bypass.json()["output"])["error"]["code"] == "authorization_required"
    )
    assert not calls
    accepted, _ = approve_call(client, body)
    assert accepted.status_code == 200
    assert json.loads(accepted.json()["receipt"]["output"])["number"] == 42
    assert len(calls) == 1


@pytest.mark.parametrize("value", [1, 0, "true", None, [], {}])
def test_http_approval_rejects_non_boolean(server_fixture, value):
    _, client, _, calls = server_fixture()
    body = make_call(client, approved=value)
    response = client.post("/api/tools/execute", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_approval"
    assert calls == []


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"session_id": "never-issued"}, "unknown_session"),
        ({"name": "delete_repository"}, "unknown_tool"),
        ({"arguments": "{}"}, "invalid_arguments"),
        ({"arguments": {}}, "invalid_arguments"),
        ({"arguments": {"title": 17}}, "invalid_arguments"),
        (
            {"arguments": {"title": "bug", "repository": "other/repo"}},
            "invalid_arguments",
        ),
        ({"call_id": ""}, "invalid_request"),
        ({"call_id": "x" * 257}, "invalid_request"),
    ],
)
def test_bad_tool_requests_do_not_run(server_fixture, changes, code):
    _, client, _, calls = server_fixture()
    body = make_call(client, **changes)
    response = client.post("/api/tools/execute", json=body)
    assert response.status_code >= 400
    assert response.json()["code"] == code
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [{}, {"sdp": ""}, {"sdp": 1}, {"sdp": " "}, {"sdp": "offer", "model": "other"}],
)
def test_invalid_session_requests_never_call_openai(server_fixture, body):
    _, client, live, _ = server_fixture()
    assert client.post("/api/live/session", json=body).status_code == 400
    assert live.requests == []


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"Origin": "https://attacker.example"}, "invalid_origin"),
        ({"Origin": "null"}, "invalid_origin"),
        ({"Origin": ""}, "invalid_origin"),
        ({"Host": "attacker.example"}, "invalid_host"),
        ({"Content-Type": "text/plain"}, "invalid_content_type"),
        ({"Sec-Fetch-Site": "cross-site"}, "invalid_origin"),
    ],
)
def test_local_boundary(server_fixture, headers, code):
    _, client, live, _ = server_fixture()
    response = client.post("/api/live/session", json={"sdp": "offer"}, headers=headers)
    assert response.status_code in {403, 415}
    assert response.json()["code"] == code
    assert live.requests == []


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"[]",
        b'{"sdp":"one","sdp":"two"}',
        b'{"sdp":NaN}',
        b'{"sdp":1e9999}',
        b"\xff",
    ],
)
def test_malformed_json(server_fixture, payload):
    _, client, live, _ = server_fixture()
    response = client.post(
        "/api/live/session",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_json"
    assert live.requests == []


def test_request_limit(server_fixture):
    _, client, live, _ = server_fixture()
    # Repeated real HTTP requests catch Windows socket resets on early rejection.
    for _ in range(10):
        response = client.post("/api/live/session", json={"sdp": "x" * 70_000})
        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"
    assert live.requests == []


def test_missing_key_and_tools_are_honest(server_fixture, settings):
    gateway = LiveClient(replace(settings, api_key=""))
    _, client, _, _ = server_fixture(
        live=gateway, api_key="", tools=ToolRegistry([], available=False)
    )
    health = client.get("/api/health").json()
    assert health == {
        "status": "ok",
        "openai_configured": False,
        "tools": "not_installed",
        "web_ready": False,
    }
    assert "UI has not been integrated" in client.get("/").text
    response = client.post("/api/live/session", json={"sdp": "offer"})
    assert response.status_code == 503
    assert response.json()["code"] == "missing_api_key"


def test_static_assets_are_isolated_from_secrets(server_fixture, settings, tmp_path):
    settings.web_dir.mkdir()
    (settings.web_dir / "index.html").write_text("<h1>Teammate UI</h1>")
    (settings.web_dir / "app.js").write_text("export const ready = true;")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=private")
    (settings.web_dir / ".env").write_text("private")
    _, client, _, _ = server_fixture()
    assert client.get("/").text == "<h1>Teammate UI</h1>"
    assert client.get("/app.js").headers["content-type"] == "text/javascript"
    for path in (
        "/.env",
        "/%2e%2e/.env",
        "/%2e%2e%5c.env",
        "/missing",
        "/src/chatty/config.py",
    ):
        assert client.get(path).status_code == 404


def test_tool_exception_is_a_receipt_without_credentials(server_fixture, settings):
    def explode(*_):
        raise RuntimeError(settings.api_key)

    _, client, _, calls = server_fixture(runner=explode)
    body = make_call(client)
    response, voice = approve_call(client, body)
    assert response.status_code == 200
    assert settings.api_key not in response.text
    assert json.loads(response.json()["receipt"]["output"])["ok"] is False
    assert client.post("/api/approvals/voice", json=voice).json() == response.json()
    assert len(calls) == 1


def test_capabilities_endpoint_exposes_only_public_metadata(server_fixture, settings):
    _, client, live, calls = server_fixture()
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"tools"}
    assert set(result["tools"]) == {"create_issue"}
    capability = result["tools"]["create_issue"]
    assert set(capability) == {"label", "requires_approval", "destructive"}
    assert capability["requires_approval"] is True
    assert capability["destructive"] is False
    assert settings.api_key not in response.text
    assert live.requests == calls == []


def test_capabilities_unavailable_does_not_look_like_empty_permissions(server_fixture):
    _, client, _, _ = server_fixture(tools=ToolRegistry([], available=False))
    response = client.get("/api/capabilities")
    assert response.status_code == 503
    assert response.json()["code"] == "tools_unavailable"


def test_project_write_http_approval_is_bound_to_exact_change(server_fixture, schemas):
    calls = []
    schema = {**schemas[0], "name": "update_project_item"}
    registry = ToolRegistry([schema], lambda *args: calls.append(args) or {"ok": True})
    _, client, _, _ = server_fixture(tools=registry)
    body = make_call(client, name="update_project_item", approved=False)
    response = client.post("/api/tools/execute", json=body)
    assert response.status_code == 200
    assert (
        json.loads(response.json()["output"])["error"]["code"]
        == "authorization_required"
    )
    assert calls == []
    changed = {
        **body,
        "approved": True,
        "arguments": {"title": "Different project update"},
    }
    assert (
        client.post("/api/tools/execute", json=changed).json()["code"]
        == "call_conflict"
    )
    body["approved"] = True
    accepted, _ = approve_call(client, body)
    assert accepted.status_code == 200
    assert json.loads(accepted.json()["receipt"]["output"])["ok"] is True
    assert len(calls) == 1
