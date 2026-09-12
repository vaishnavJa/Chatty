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


def test_complete_http_handoff_and_duplicate_receipts(server_fixture):
    _, client, live, calls = server_fixture()
    body = make_call(client)
    first = client.post("/api/tools/execute", json=body)
    again = client.post("/api/tools/execute", json=body)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert set(first.json()) == {"call_id", "output"}
    assert isinstance(first.json()["output"], str)
    assert json.loads(first.json()["output"])["number"] == 42
    assert len(calls) == 1
    assert live.requests[0][0] == "v=0\r\noffer\r\n"


def test_http_review_can_approve_same_call_after_denial(server_fixture):
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
    accepted = client.post("/api/tools/execute", json=body)
    assert accepted.status_code == 200
    assert json.loads(accepted.json()["output"])["number"] == 42
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
    response = client.post("/api/tools/execute", json=body)
    assert response.status_code == 200
    assert settings.api_key not in response.text
    assert json.loads(response.json()["output"])["ok"] is False
    assert client.post("/api/tools/execute", json=body).json() == response.json()
    assert len(calls) == 1
