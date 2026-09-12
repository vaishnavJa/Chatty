"""Registry authorization and durable dispatch; all GitHub effects are mocked."""

import json
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from chatty.agents import tools
from chatty.integrations.github import project_tools, repository_tools, writes
from chatty.integrations.github.dedup import CallLedger

SHA = "a" * 40
WRITE_ARGUMENTS = {
    "create_issue": {"title": "Example", "body": "Description"},
    "update_issue": {"issue_number": 1, "title": "Updated"},
    "add_issue_comment": {"issue_number": 1, "body": "Comment"},
    "update_issue_comment": {"comment_id": 1, "body": "Comment"},
    "create_pull_request": {
        "title": "Example",
        "body": "Description",
        "head": "codex/example",
        "base": "main",
    },
    "update_pull_request": {"pull_number": 1, "title": "Updated"},
    "merge_pull_request": {"pull_number": 1, "expected_head_sha": SHA},
    "create_branch": {"branch": "codex/example", "sha": SHA},
    "delete_branch": {"branch": "codex/example"},
    "update_repository_file": {
        "path": "README.md",
        "branch": "codex/example",
        "content": "Example",
        "message": "Clarify the example",
        "expected_sha": SHA,
    },
    "delete_repository_file": {
        "path": "example.txt",
        "branch": "codex/example",
        "message": "Remove an obsolete example",
        "expected_sha": SHA,
    },
    "rerun_workflow": {"run_id": 1},
    "add_project_item": {"url": "https://github.com/vaishnavJa/Chatty/issues/1"},
    "update_project_item": {
        "item_id": "PVTI_example",
        "field_name": "Status",
        "value": "Done",
    },
    "archive_project_item": {"item_id": "PVTI_example", "archived": True},
    "remove_project_item": {"item_id": "PVTI_example"},
    "update_project_details": {"description": "Updated description"},
}


def result(name, arguments, **kwargs):
    return json.loads(
        tools.execute_call("session", "call", name, arguments, **kwargs)["output"]
    )


def test_registry_is_complete_disjoint_and_has_valid_schemas():
    assert set(WRITE_ARGUMENTS) == tools.WRITE_TOOL_NAMES
    assert set(tools.TOOLS) == tools.READ_TOOL_NAMES | tools.WRITE_TOOL_NAMES
    assert not tools.READ_TOOL_NAMES & tools.WRITE_TOOL_NAMES
    assert set(tools.TOOL_CAPABILITIES) == set(tools.TOOLS)
    assert len(tools.TOOLS) == len(tools.TOOL_SCHEMAS)
    for schema in tools.TOOL_SCHEMAS:
        name = schema["name"]
        Draft202012Validator.check_schema(schema["parameters"])
        assert schema["parameters"]["additionalProperties"] is False
        assert (
            not {
                "repository",
                "owner",
                "project_number",
                "explicit_user_request",
                "command",
                "endpoint",
            }
            & schema["parameters"]["properties"].keys()
        )
        assert tools.TOOL_CAPABILITIES[name]["requires_approval"] == (
            name in tools.WRITE_TOOL_NAMES
        )


@pytest.mark.parametrize("name,arguments", WRITE_ARGUMENTS.items())
def test_every_write_requires_literal_intent_before_ledger(name, arguments):
    ledger = Mock()
    for intent in (False, None, 0, 1, "true"):
        response = result(name, arguments, explicit_user_request=intent, ledger=ledger)
        assert response["error"]["code"] == "authorization_required"
    ledger.run.assert_not_called()


@pytest.mark.parametrize("name,arguments", WRITE_ARGUMENTS.items())
def test_every_write_requires_a_durable_ledger(name, arguments, monkeypatch):
    monkeypatch.delenv("CHATTY_GITHUB_LEDGER_PATH", raising=False)
    response = result(name, arguments, explicit_user_request=True)
    assert response["error"]["code"] == "ledger_not_configured"


@pytest.mark.parametrize("name,arguments", WRITE_ARGUMENTS.items())
def test_every_write_replays_once_across_ledger_instances(
    name, arguments, monkeypatch, tmp_path
):
    effect = Mock(return_value={"changed": True})
    if name == "create_issue":
        monkeypatch.setattr(writes, "create_issue", effect)
    else:
        module = (
            project_tools if name in project_tools.WRITE_TOOLS else repository_tools
        )
        monkeypatch.setattr(module, "execute", effect)
    path = tmp_path / "calls.sqlite3"
    first = result(name, arguments, explicit_user_request=True, ledger=CallLedger(path))
    second = result(
        name, arguments, explicit_user_request=True, ledger=CallLedger(path)
    )
    assert first == second
    assert first["ok"] is True
    effect.assert_called_once()


@pytest.mark.parametrize("name,arguments", WRITE_ARGUMENTS.items())
def test_unexpected_mutation_failures_are_uncertain_and_cached(
    name, arguments, monkeypatch, tmp_path
):
    effect = Mock(side_effect=RuntimeError("private-key-material"))
    if name == "create_issue":
        monkeypatch.setattr(writes, "create_issue", effect)
    else:
        module = (
            project_tools if name in project_tools.WRITE_TOOLS else repository_tools
        )
        monkeypatch.setattr(module, "execute", effect)
    path = tmp_path / "calls.sqlite3"
    first = result(name, arguments, explicit_user_request=True, ledger=CallLedger(path))
    assert first["error"]["uncertain"] is True
    assert "private-key-material" not in json.dumps(first)
    assert (
        result(name, arguments, explicit_user_request=True, ledger=CallLedger(path))
        == first
    )
    effect.assert_called_once()


@pytest.mark.parametrize(
    "name,module",
    [("get_repository", repository_tools), ("get_project", project_tools)],
)
def test_read_dispatch_preserves_adapter_data_without_reservation(
    name, module, monkeypatch
):
    data = {"evidence": "fixture"}
    read = Mock(return_value=data)
    monkeypatch.setattr(module, "execute", read)
    ledger = Mock()
    assert result(name, {}, ledger=ledger)["data"] == data
    ledger.run.assert_not_called()
    read.assert_called_once_with(name, {})


def test_screen_tool_requires_browser_context_and_never_invents_content():
    response = result(
        "read_meeting_screen", {"question": "What is the presenter showing?"}
    )
    assert response["error"]["code"] == "screen_context_required"
    assert response["error"]["uncertain"] is False
    assert "data" not in response


@pytest.mark.parametrize(
    "arguments", [{}, {"question": " "}, {"question": "x", "frame": "untrusted"}]
)
def test_screen_tool_rejects_missing_question_or_model_supplied_frame(arguments):
    assert (
        result("read_meeting_screen", arguments)["error"]["code"] == "invalid_arguments"
    )
