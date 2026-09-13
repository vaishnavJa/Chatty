"""Offline contract rehearsal: real localhost server + real browser controller.

Live utterances/function calls and classifier answers are explicitly scripted.
The real tool adapter and durable ledger run against a fake GitHub transport.
This is not proof of model reasoning, recognition, routing, or meeting audibility.
"""

import copy
import json
import shutil
import subprocess
import threading
from pathlib import Path

import httpx
import pytest

from chatty.approval_language import ApprovalLanguage
from chatty.config import Settings
from chatty.integrations.github import repository_tools, transport, writes
from chatty.integrations.github.transport import GitHubToolError
from chatty.server import create_server

ROOT = Path(__file__).resolve().parents[2]
ISSUE_URL = "https://github.com/vaishnavJa/Chatty/issues/42"


class ScriptedLive:
    """Session negotiation only; the JS driver explicitly supplies model output."""

    def __init__(self):
        self.created = 0

    def create_session(self, sdp, schemas):
        assert sdp == "offline-contract-rehearsal"
        assert any(schema["name"] == "create_issue" for schema in schemas)
        self.created += 1
        return {"session": {"id": f"rehearsal-{self.created}"}}

    def close(self):
        pass


@pytest.fixture
def rehearsal_server(tmp_path, monkeypatch):
    """All provider boundaries are replaced before the real server starts."""
    operations = []
    classifier_requests = []
    issue = {
        "number": 42,
        "html_url": ISSUE_URL,
        "title": "Login retry bug",
        "body": "Retry after session expiry fails.",
        "state": "open",
        "user": {"login": "meeting-fixture"},
        "assignees": [{"login": "ronly2460"}],
        "labels": [],
    }

    def fake_api(method, suffix="", *, payload=None, query=None, empty=False):
        assert suffix == "issues/42", (method, suffix)
        assert method in {"GET", "PATCH"}
        operations.append({"method": method, "payload": copy.deepcopy(payload)})
        if method == "PATCH":
            issue.update(copy.deepcopy(payload))
            if "assignees" in payload:
                issue["assignees"] = [
                    {"login": login} for login in payload["assignees"]
                ]
        return copy.deepcopy(issue)

    def fake_issue_cli(args):
        assert args[:2] == ["issue", "create"]
        assert args[args.index("--repo") + 1] == "vaishnavJa/Chatty"
        title = next(value[8:] for value in args if value.startswith("--title="))
        body = Path(args[args.index("--body-file") + 1]).read_text()
        operations.append({"method": "CREATE", "title": title, "body": body})
        if title == "Permission failure rehearsal":
            raise GitHubToolError(
                "permission_denied",
                "GitHub denied access. Check repository permissions.",
            )
        return ISSUE_URL

    def forbidden_provider(*args, **kwargs):
        raise AssertionError(
            "An unmocked provider was reached during offline rehearsal"
        )

    def classifier_reply(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][0]["content"][0]["text"])
        classifier_requests.append(context)
        # Explicit fixtures, not imitation of real model interpretation.
        if context["mode"] == "prompt":
            assert context["assistant_prompt"] == (
                "I can file the login retry problem we discussed. Shall I go ahead?"
            )
            intent = "ready"
        else:
            assert context["participant_reply"] == "You have my green light."
            intent = "approve"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"intent": intent}),
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(repository_tools, "_api", fake_api)
    monkeypatch.setattr(writes, "run_gh", fake_issue_cli)
    monkeypatch.setattr(transport, "run_gh", forbidden_provider)
    settings = Settings(
        api_key="offline-fixture-key",
        port=0,
        ledger_path=tmp_path / "ledger.sqlite3",
        web_dir=ROOT / "web",
    )
    classifier = httpx.Client(transport=httpx.MockTransport(classifier_reply))
    server = create_server(settings, live_client=ScriptedLive())
    server.app.approvals.language = ApprovalLanguage(settings, http=classifier)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, operations, classifier_requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        classifier.close()


def run_controller(base, scenario):
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for the cross-component rehearsal")
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name("controller_rehearsal.mjs")),
            base,
            scenario,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "scripted-provider-contract-rehearsal"
    assert report["scenario"] == scenario
    return report


def test_group_evidence_question_revision_and_single_write(rehearsal_server):
    base, operations, classifiers = rehearsal_server
    report = run_controller(base, "group-decision")
    assert report["checks"] >= 12
    writes_seen = [row for row in operations if row["method"] == "PATCH"]
    assert len(writes_seen) == 1
    assert writes_seen[0]["payload"]["assignees"] == ["karimkohel"]
    assert writes_seen[0]["payload"]["title"] == "Handle expired login retries"
    assert "meeting-3" in writes_seen[0]["payload"]["body"]
    assert len([row for row in operations if row["method"] == "GET"]) == 1
    assert any(
        row.get("participant_reply") == "You have my green light."
        for row in classifiers
    )


def test_permission_failure_keeps_draft_and_never_claims_success(rehearsal_server):
    base, operations, _ = rehearsal_server
    report = run_controller(base, "permission-failure")
    assert report["checks"] >= 4
    assert len(operations) == 1
    assert operations[0]["method"] == "CREATE"


def test_delayed_completed_receipt_cannot_restart_speech_after_stop(rehearsal_server):
    base, operations, classifiers = rehearsal_server
    report = run_controller(base, "delayed-result")
    assert report["checks"] >= 5
    assert len(operations) == 1
    assert operations[0]["method"] == "CREATE"
    assert any(row["mode"] == "prompt" for row in classifiers)
