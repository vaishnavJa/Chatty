import base64
import json
from dataclasses import replace

import httpx
import pytest

from chatty.integrations.meeting_vision import (
    FRAME_PREFIX,
    MAX_FRAME_BYTES,
    MeetingVisionClient,
    VisionError,
    validate_frame,
)

NOW = 1_800_000_000.0
# Minimal SOF header for mocked HTTP, not a complete decodable photo.
JPEG = bytes.fromhex("ffd8 ffc0 0011 08 02d0 0500 03 011100 021100 031100 ffd9")


def frame(**updates):
    return {
        "image_data_url": FRAME_PREFIX + base64.b64encode(JPEG).decode(),
        "width": 1280,
        "height": 720,
        "captured_at": NOW * 1000,
        **updates,
    }


def success(text="The slide shows three blue bars."):
    return {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
    }


def test_responses_gets_actual_image_bytes_and_no_live_events_or_tools(settings):
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == f"Bearer {settings.api_key}"
        body = json.loads(request.content)
        assert body["model"] == settings.vision_model
        assert body["store"] is False
        assert "tools" not in body
        content = body["input"][0]["content"]
        assert content[0] == {"type": "input_text", "text": "Explain these bars"}
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"] == frame()["image_data_url"]
        assert content[1]["detail"] == "high"
        return httpx.Response(200, json=success())

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = MeetingVisionClient(settings, http=http, clock=lambda: NOW)
        actual = client.describe(frame(), "Explain these bars")
    assert len(calls) == 1
    assert actual == {
        "ok": True,
        "answer": "The slide shows three blue bars.",
        "captured_at": NOW * 1000,
        "source": "selected_meeting_tab",
        "mode": "snapshot",
    }
    assert "image_data_url" not in actual
    assert not any("frame" in key for key in client.__dict__)


@pytest.mark.parametrize(
    "updates",
    [
        {"image_data_url": "https://example.com/screen.jpg"},
        {"image_data_url": "data:image/png;base64,abcd"},
        {"image_data_url": FRAME_PREFIX + "not valid base64!!!"},
        {"image_data_url": FRAME_PREFIX + base64.b64encode(b"not a JPEG").decode()},
        {
            "image_data_url": FRAME_PREFIX
            + base64.b64encode(JPEG + b"x" * MAX_FRAME_BYTES).decode()
        },
        {"width": 1281},
        {"width": 1279},
        {
            "image_data_url": FRAME_PREFIX
            + base64.b64encode(b"\xff\xd8\xff\xd9").decode()
        },
        {"height": 0},
        {"width": True},
        {"captured_at": NOW * 1000 - 15_001},
        {"captured_at": NOW * 1000 + 2001},
        {"captured_at": float("nan")},
        {"captured_at": True},
        {"extra": "field"},
    ],
)
def test_invalid_or_stale_frame_never_reaches_openai(settings, updates):
    def respond(_):
        pytest.fail("An invalid frame must never leave the local server")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(VisionError):
            MeetingVisionClient(settings, http=http, clock=lambda: NOW).describe(
                frame(**updates), "What is visible?"
            )


def test_validator_returns_separate_frame_metadata():
    value = frame()
    assert validate_frame(value, now_ms=NOW * 1000) == value
    assert validate_frame(value, now_ms=NOW * 1000) is not value


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_upstream_error_is_sanitized_and_not_retried(settings, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=f"echo {settings.api_key} {frame()}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(VisionError) as caught:
            MeetingVisionClient(settings, http=http, clock=lambda: NOW).describe(
                frame(), "Read it"
            )
    assert len(calls) == 1
    assert settings.api_key not in str(caught.value)
    assert FRAME_PREFIX not in str(caught.value)


@pytest.mark.parametrize(
    "body", [{}, None, [], {"status": "incomplete", "output": []}, success("")]
)
def test_bad_responses_are_not_reported_as_visual_answers(settings, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(VisionError, match="complete answer"):
            MeetingVisionClient(settings, http=http, clock=lambda: NOW).describe(
                frame(), "Read it"
            )


def test_missing_key_rejects_before_network(settings):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("No request expected"))
    ) as http:
        with pytest.raises(VisionError, match="OPENAI_API_KEY"):
            MeetingVisionClient(
                replace(settings, api_key=""), http=http, clock=lambda: NOW
            ).describe(frame(), "Read it")


def test_accidental_configured_secret_echo_is_redacted(settings):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=success(settings.api_key))
        )
    ) as http:
        result = MeetingVisionClient(settings, http=http, clock=lambda: NOW).describe(
            frame(), "Read it"
        )
    assert result["answer"] == "[redacted]"


@pytest.mark.parametrize(
    "error,status", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)]
)
def test_network_failures_have_safe_errors(settings, error, status):
    def respond(request):
        raise error(settings.api_key, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(VisionError) as caught:
            MeetingVisionClient(settings, http=http, clock=lambda: NOW).describe(
                frame(), "Read it"
            )
    assert caught.value.status == status
    assert settings.api_key not in str(caught.value)
