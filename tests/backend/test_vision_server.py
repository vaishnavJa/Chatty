import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from chatty.agents.tools import TOOL_SCHEMAS
from chatty.integrations.gpt_live.executor import ToolRegistry
from chatty.integrations.meeting_vision import FRAME_PREFIX, VisionError, validate_frame

JPEG = bytes.fromhex("ffd8 ffc0 0011 08 02d0 0500 03 011100 021100 031100 ffd9")


def snapshot(data=JPEG):
    return {
        "image_data_url": FRAME_PREFIX + base64.b64encode(data).decode(),
        "width": 1280,
        "height": 720,
        "captured_at": time.time() * 1000,
    }


class FakeVision:
    def __init__(self):
        self.calls = []
        self.callback = None

    def describe(self, frame, question):
        validate_frame(frame)
        self.calls.append(question)
        if self.callback:
            return self.callback(frame, question)
        return {
            "ok": True,
            "answer": "The current slide has a blue shape.",
            "captured_at": frame["captured_at"],
            "source": "selected_meeting_tab",
            "mode": "snapshot",
        }

    def close(self):
        pass


@pytest.fixture
def vision_server(server_fixture, tmp_path):
    def start(names=("read_meeting_screen", "list_open_issues")):
        schemas = [schema for schema in TOOL_SCHEMAS if schema["name"] in names]
        registry = ToolRegistry(schemas, lambda name, arguments: {"ok": True})
        server, http, live, _ = server_fixture(
            tools=registry, ledger_path=tmp_path / "vision-ledger.sqlite3"
        )
        server.app.vision.close()
        server.app.vision = fake = FakeVision()
        session_id = http.post("/api/live/session", json={"sdp": "offer"}).json()[
            "session"
        ]["id"]
        body = {
            "session_id": session_id,
            "call_id": "screen-question-one",
            "question": "What color is the shape?",
            "frame": snapshot(),
        }
        return server, http, fake, body

    return start


def test_snapshot_route_returns_receipt_and_reuses_it_without_storing_pixels(
    vision_server,
):
    server, http, vision, body = vision_server()
    first = http.post("/api/vision/analyze", json=body)
    assert first.status_code == 200
    receipt = first.json()
    assert receipt["call_id"] == body["call_id"]
    assert (
        json.loads(receipt["output"])["answer"] == "The current slide has a blue shape."
    )
    # A retry gets the original result even if its captured image has aged.
    body["frame"]["captured_at"] -= 20_000
    second = http.post("/api/vision/analyze", json=body)
    assert second.json() == receipt
    assert len(vision.calls) == 1
    call = server.app.executor.sessions[body["session_id"]].calls[body["call_id"]]
    assert "image_data_url" not in call.fingerprint
    assert FRAME_PREFIX not in repr(call.result.result())
    assert not server.app.settings.ledger_path.exists()


@pytest.mark.parametrize("kind", ["unknown", "expired", "not_registered"])
def test_unavailable_session_or_tool_never_calls_vision(vision_server, kind):
    server, http, vision, body = vision_server(
        names=("list_open_issues",)
        if kind == "not_registered"
        else ("read_meeting_screen",)
    )
    if kind == "unknown":
        body["session_id"] = "different-session"
    elif kind == "expired":
        server.app.executor.sessions[body["session_id"]].created -= (
            server.app.settings.session_ttl_seconds + 1
        )
    response = http.post("/api/vision/analyze", json=body)
    assert response.status_code == (400 if kind == "not_registered" else 404)
    assert vision.calls == []


def test_same_call_cannot_change_question_or_collide_with_repo_tool(vision_server):
    _, http, vision, body = vision_server()
    assert http.post("/api/vision/analyze", json=body).status_code == 200
    body["question"] = "What is the title?"
    assert http.post("/api/vision/analyze", json=body).status_code == 409
    normal = {
        "session_id": body["session_id"],
        "call_id": "repo-call",
        "name": "list_open_issues",
        "arguments": {},
    }
    assert http.post("/api/tools/execute", json=normal).status_code == 200
    body["call_id"] = "repo-call"
    assert http.post("/api/vision/analyze", json=body).status_code == 409
    assert len(vision.calls) == 1


def test_normal_tool_route_cannot_manufacture_or_reserve_a_screen_answer(vision_server):
    server, http, vision, body = vision_server()
    normal = {
        "session_id": body["session_id"],
        "call_id": body["call_id"],
        "name": "read_meeting_screen",
        "arguments": {"question": body["question"]},
    }
    response = http.post("/api/tools/execute", json=normal)
    assert response.status_code == 400
    assert response.json()["code"] == "screen_context_required"
    assert body["call_id"] not in server.app.executor.sessions[body["session_id"]].calls
    assert vision.calls == []


def test_concurrent_duplicate_screen_requests_run_once(vision_server):
    server, _, vision, body = vision_server()
    entered = threading.Event()
    release = threading.Event()

    def hold(frame, question):
        entered.set()
        assert release.wait(3)
        return {"ok": True, "answer": "Only one inference"}

    vision.callback = hold
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(server.app.analyze_vision, body)
        assert entered.wait(2)
        second = pool.submit(server.app.analyze_vision, body)
        release.set()
        assert first.result(timeout=3) == second.result(timeout=3)
    assert len(vision.calls) == 1


def test_same_call_id_in_a_new_session_never_reuses_old_screen(vision_server):
    _, http, vision, body = vision_server()
    first = http.post("/api/vision/analyze", json=body)
    assert first.status_code == 200
    body["session_id"] = http.post(
        "/api/live/session", json={"sdp": "new offer"}
    ).json()["session"]["id"]
    body["question"] = "What is visible in the new meeting?"
    assert http.post("/api/vision/analyze", json=body).status_code == 200
    assert len(vision.calls) == 2


def test_vision_errors_are_cached_and_keep_upstream_details_private(vision_server):
    _, http, vision, body = vision_server()

    def fail(frame, question):
        raise VisionError(429, "vision_request_rejected", "Quota reached.")

    vision.callback = fail
    result = http.post("/api/vision/analyze", json=body).json()
    assert json.loads(result["output"])["error"]["code"] == "vision_request_rejected"
    assert http.post("/api/vision/analyze", json=body).json() == result
    assert len(vision.calls) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://untrusted.example"},
        {"Host": "untrusted.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_vision_preserves_host_and_origin_guards(vision_server, headers):
    _, http, vision, body = vision_server()
    assert (
        http.post("/api/vision/analyze", json=body, headers=headers).status_code == 403
    )
    assert vision.calls == []


def test_vision_large_body_allowance_does_not_apply_to_other_routes(vision_server):
    _, http, vision, body = vision_server()
    # Two JPEG comments before SOF keep valid bounded header metadata >64 KiB.
    comment = b"\xff\xfe" + (40_002).to_bytes(2, "big") + b"x" * 40_000
    body["frame"] = snapshot(JPEG[:2] + comment + comment + JPEG[2:])
    assert len(json.dumps(body)) > 65_536
    assert http.post("/api/vision/analyze", json=body).status_code == 200
    assert len(vision.calls) == 1
    assert http.post("/api/tools/execute", json=body).status_code == 413
    assert http.post("/api/live/session", json={"sdp": "x" * 66_000}).status_code == 413
    assert (
        http.post(
            "/api/vision/analyze", json={**body, "padding": "x" * (384 * 1024)}
        ).status_code
        == 413
    )


@pytest.mark.parametrize(
    "change",
    [
        {"frame": None},
        {"question": ""},
        {"session_id": ""},
        {"call_id": ""},
        {"approved": True},
    ],
)
def test_invalid_route_fields_are_rejected_before_any_vision(vision_server, change):
    _, http, vision, body = vision_server()
    assert http.post("/api/vision/analyze", json={**body, **change}).status_code == 400
    assert vision.calls == []


def test_stale_initial_snapshot_never_reaches_model(vision_server):
    _, http, vision, body = vision_server()
    body["frame"]["captured_at"] -= 20_000
    response = http.post("/api/vision/analyze", json=body)
    assert json.loads(response.json()["output"])["error"]["code"] == "stale_frame"
    assert vision.calls == []
