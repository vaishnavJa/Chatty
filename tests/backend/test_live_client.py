import httpx
import pytest

from chatty.integrations.gpt_live.client import LIVE_SESSIONS_URL, LiveClient, LiveError


def test_live_payload_and_public_response(settings, schemas):
    import json

    def respond(request):
        assert str(request.url) == LIVE_SESSIONS_URL
        assert request.headers["authorization"] == "Bearer test-openai-secret"
        payload = json.loads(request.content)
        assert payload["transport"] == {"type": "webrtc", "sdp": "exact offer\r\n"}
        assert payload["session"]["model"] == "gpt-live-1"
        assert "tools" not in payload["session"]
        delegation = payload["session"]["delegation"]
        assert delegation["type"] == "responses"
        assert delegation["responses"]["model"] == settings.backend_model
        assert delegation["responses"]["tools"] == schemas
        assert "explicit spoken request" in delegation["responses"]["instructions"]
        assert delegation["responses"]["parallel_tool_calls"] is False
        for instructions in (
            payload["session"]["instructions"],
            delegation["responses"]["instructions"],
        ):
            instructions = " ".join(instructions.split())
            assert "A mutation tool call proposes a change" in instructions
            assert "Do not collect approval yourself before" in instructions
            assert "Follow-up questions and commands do not need" in instructions
            assert "An unclear answer" in instructions
            assert "do not recite" in instructions.lower()
            assert "short, natural summary" in instructions
            assert "one addressed request, then return to quiet" not in instructions
            assert "exact approval in the browser UI" not in instructions
            assert "must await exact browser UI approval" not in instructions
        voice_instructions = payload["session"]["instructions"]
        assert "The application mutes your output and plays one brief 'Okay'" in (
            " ".join(voice_instructions.split())
        )
        assert "Input remains open" in voice_instructions
        assert (
            "Never add approval fields to tool arguments"
            in (delegation["responses"]["instructions"])
        )
        return httpx.Response(
            201,
            json={
                "session": {"id": "opaque-123", "private": settings.api_key},
                "transport": {"type": "webrtc", "sdp": "exact answer\r\n"},
                "api_key": settings.api_key,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        actual = LiveClient(settings, http=http).create_session(
            "exact offer\r\n", schemas
        )
    assert actual == {
        "session": {"id": "opaque-123"},
        "transport": {"type": "webrtc", "sdp": "exact answer\r\n"},
    }


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_upstream_failures_are_sanitized_and_not_retried(settings, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=f"Credential: {settings.api_key}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(LiveError) as caught:
            LiveClient(settings, http=http).create_session("offer", [])
    assert settings.api_key not in str(caught.value)
    assert len(calls) == 1
    assert caught.value.status == (502 if status >= 500 else status)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"session": {"id": "x"}},
        {"session": {"id": ""}, "transport": {"type": "webrtc", "sdp": "answer"}},
        {"session": {"id": "x"}, "transport": {"type": "other", "sdp": "answer"}},
    ],
)
def test_invalid_answers_are_rejected(settings, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(201, json=body))
    ) as http:
        with pytest.raises(LiveError, match="invalid Live session response"):
            LiveClient(settings, http=http).create_session("offer", [])


@pytest.mark.parametrize(
    "error, status", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)]
)
def test_network_errors(settings, error, status):
    def respond(request):
        raise error(settings.api_key, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(LiveError) as caught:
            LiveClient(settings, http=http).create_session("offer", [])
    assert caught.value.status == status
    assert settings.api_key not in str(caught.value)
