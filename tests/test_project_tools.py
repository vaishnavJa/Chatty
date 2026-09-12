"""Exercise configured-project boundaries with fixture-only subprocess responses."""

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from chatty.integrations.github import project_tools as projects
from chatty.integrations.github.transport import GitHubToolError

PROJECT = {
    "id": "PVT_fixture",
    "number": 73,
    "owner": {"login": "fixture-owner", "type": "User"},
    "title": "Fixture project",
    "url": "https://github.com/users/fixture-owner/projects/73",
    "public": False,
}
ITEM = {"id": "PVTI_fixture", "isArchived": False, "project": {"id": "PVT_fixture"}}
FIELDS = [
    {
        "id": "PVTSSF_status",
        "name": "Status",
        "dataType": "SINGLE_SELECT",
        "options": [
            {"id": "fixture-todo", "name": "Todo"},
            {"id": "fixture-done", "name": "Done"},
        ],
    },
    {"id": "PVTF_text", "name": "Notes", "dataType": "TEXT"},
    {"id": "PVTF_number", "name": "Estimate", "dataType": "NUMBER"},
    {"id": "PVTF_date", "name": "Due", "dataType": "DATE"},
    {"id": "PVTF_title", "name": "Title", "dataType": "TITLE"},
]


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv("CHATTY_PROJECT_OWNER", "fixture-owner")
    monkeypatch.setenv("CHATTY_PROJECT_NUMBER", "73")
    state = {
        "calls": [],
        "project": copy.deepcopy(PROJECT),
        "item": copy.deepcopy(ITEM),
        "fields": copy.deepcopy(FIELDS),
        "items": {"items": [{"id": ITEM["id"]}], "totalCount": 2},
        "write_response": {"id": ITEM["id"]},
        "payloads": [],
        "paths": [],
    }

    def run(command, **kwargs):
        assert command[0] == "gh"
        assert kwargs["shell"] is False
        assert kwargs["env"]["GH_HOST"] == "github.com"
        assert kwargs["env"]["GH_PROMPT_DISABLED"] == "1"
        state["calls"].append(command[1:])
        args = command[1:]
        if args[:2] == ["project", "view"]:
            result = state["project"]
        elif args[:2] == ["project", "item-list"]:
            result = state["items"]
        elif args[:2] == ["api", "graphql"]:
            assert args[args.index("--method") + 1] == "POST"
            if "--input" in args:
                path = Path(args[args.index("--input") + 1])
                assert path.stat().st_mode & 0o777 == 0o600
                payload = json.loads(path.read_text())
                state["payloads"].append(payload)
                state["paths"].append(path)
                result = {
                    "data": {
                        "updateProjectV2": {
                            "projectV2": {
                                "id": PROJECT["id"],
                                **{
                                    key: value
                                    for key, value in payload["variables"][
                                        "input"
                                    ].items()
                                    if key != "projectId"
                                },
                            }
                        }
                    }
                }
            elif "query=" + projects._FIELDS_QUERY in args:
                assert "project=" + PROJECT["id"] in args
                result = {
                    "data": {
                        "node": {
                            "id": PROJECT["id"],
                            "fields": {
                                "nodes": state["fields"],
                                "totalCount": len(state["fields"]),
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            },
                        }
                    }
                }
                result = state.get("fields_response", result)
            else:
                assert "query=" + projects._ITEM_QUERY in args
                assert "item=" + ITEM["id"] in args
                result = {"data": {"node": state["item"]}}
        else:
            if "write_error" in state:
                raise state["write_error"]
            if "write_stderr" in state:
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr=state["write_stderr"]
                )
            result = state["write_response"]
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(result), stderr=""
        )

    monkeypatch.setattr(projects.transport.subprocess, "run", run)
    return state


def mutation_calls(boundary):
    return [
        call
        for call in boundary["calls"]
        if call[:2]
        in [
            ["project", "item-edit"],
            ["project", "item-add"],
            ["project", "item-delete"],
            ["project", "item-archive"],
        ]
        or "--input" in call
    ]


def test_exports_consistent_and_every_write_requires_approval():
    names = {schema["name"] for schema in projects.TOOL_SCHEMAS}
    assert names == projects.READ_TOOLS | projects.WRITE_TOOLS
    assert not projects.READ_TOOLS & projects.WRITE_TOOLS
    assert names == projects.TOOL_CAPABILITIES.keys()
    for name in names:
        assert projects.TOOL_CAPABILITIES[name]["requires_approval"] is (
            name in projects.WRITE_TOOLS
        )
    assert projects.TOOL_CAPABILITIES["remove_project_item"]["destructive"]
    assert all(
        schema["parameters"]["additionalProperties"] is False
        for schema in projects.TOOL_SCHEMAS
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_project", {}),
        ([], {}),
        ("get_project", []),
        ("get_project", {"owner": "other"}),
        ("get_project", {"project_id": "PVT_other"}),
        ("list_project_items", {"limit": True}),
        ("list_project_items", {"limit": 101}),
        ("list_project_items", {"limit": 0}),
        ("list_project_items", {"limit": 1.5}),
        (
            "update_project_item",
            {"item_id": "--repo=other", "field_name": "Status", "value": "Done"},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": " ", "value": "Done"},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Status", "value": True},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Estimate", "value": float("nan")},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Estimate", "value": float("inf")},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Notes", "value": "\x00"},
        ),
        (
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Notes", "value": "\ud800"},
        ),
        ("archive_project_item", {"item_id": ITEM["id"], "archived": "false"}),
        ("remove_project_item", {}),
        ("update_project_details", {}),
        ("update_project_details", {"title": " "}),
        ("update_project_details", {"public": True}),
        ("update_project_details", {"description": "x" * 1025}),
    ],
)
def test_invalid_arguments_fail_without_transport(boundary, name, args):
    assert projects.validate(name, args)["ok"] is False
    with pytest.raises(GitHubToolError):
        projects.execute(name, args)
    assert boundary["calls"] == []


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/other/repo/issues/1",
        "http://github.com/vaishnavJa/Chatty/issues/1",
        "https://github.com/vaishnavJa/Chatty/issues/0",
        "https://github.com/vaishnavJa/Chatty/issues/01",
        "https://github.com/vaishnavJa/Chatty/issues/1?repo=other",
        "https://github.com/vaishnavJa/Chatty/issues/1#x",
        "https://github.com@evil.test/vaishnavJa/Chatty/issues/1",
        "https://github.com/vaishnavJa/Chatty/pulls/1",
        "https://github.com/vaishnavJa/Chatty/issues/1/",
        "https://github.com/vaishnavJa/Chatty/issues/1\n",
    ],
)
def test_add_rejects_urls_outside_repository(boundary, url):
    with pytest.raises(GitHubToolError):
        projects.execute("add_project_item", {"url": url})
    assert boundary["calls"] == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("CHATTY_PROJECT_OWNER", ""),
        ("CHATTY_PROJECT_OWNER", "@me"),
        ("CHATTY_PROJECT_OWNER", "--owner=other"),
        ("CHATTY_PROJECT_NUMBER", ""),
        ("CHATTY_PROJECT_NUMBER", "0"),
        ("CHATTY_PROJECT_NUMBER", "01"),
        ("CHATTY_PROJECT_NUMBER", "2147483648"),
    ],
)
def test_configuration_cannot_fall_back_to_arbitrary_project(
    boundary, monkeypatch, key, value
):
    monkeypatch.setenv(key, value)
    with pytest.raises(GitHubToolError, match="Configure") as caught:
        projects.execute("get_project", {})
    assert caught.value.code == "project_not_configured"
    assert not boundary["calls"]


def test_project_reads_use_server_selection_and_preserve_factual_data(boundary):
    assert projects.execute("get_project", {}) == PROJECT
    assert boundary["calls"][0] == [
        "project",
        "view",
        "73",
        "--owner",
        "fixture-owner",
        "--format",
        "json",
    ]
    fields = projects.execute("list_project_fields", {})
    assert fields["fields"][0]["options"][1] == {"id": "fixture-done", "name": "Done"}
    items = projects.execute("list_project_items", {"limit": 1})
    assert items["truncated"] is True
    assert boundary["calls"][-1][-2:] == ["--limit", "1"]


@pytest.mark.parametrize(
    "change", [{"number": 74}, {"owner": {"login": "other"}}, {"id": ""}]
)
def test_rejects_unexpected_project_identity(boundary, change):
    boundary["project"].update(change)
    with pytest.raises(GitHubToolError) as caught:
        projects.execute("list_project_fields", {})
    assert caught.value.code == "invalid_response"
    assert len(boundary["calls"]) == 1


@pytest.mark.parametrize(
    "name,args",
    [
        ("update_project_item", {"field_name": "Status", "value": "Done"}),
        ("archive_project_item", {"archived": True}),
        ("remove_project_item", {}),
    ],
)
@pytest.mark.parametrize(
    "item",
    [None, {"id": ITEM["id"], "project": {"id": "PVT_other"}, "isArchived": False}],
)
def test_all_existing_item_writes_require_membership(boundary, name, args, item):
    boundary["item"] = item
    with pytest.raises(GitHubToolError) as caught:
        projects.execute(name, {"item_id": ITEM["id"], **args})
    assert caught.value.code == "item_not_in_project"
    assert not mutation_calls(boundary)


@pytest.mark.parametrize(
    "field,value,flag",
    [
        ("sTaTuS", "dOnE", "--single-select-option-id=fixture-done"),
        (
            "Notes",
            "--visibility=PUBLIC\n$(whoami) `id` café",
            "--text=--visibility=PUBLIC\n$(whoami) `id` café",
        ),
        ("Estimate", 0, "--number=0"),
        ("Estimate", -1.5, "--number=-1.5"),
        ("Due", "2028-02-29", "--date=2028-02-29"),
        ("Status", None, "--clear"),
    ],
)
def test_typed_field_updates_use_verified_ids_and_literal_arguments(
    boundary, field, value, flag
):
    result = projects.execute(
        "update_project_item",
        {"item_id": ITEM["id"], "field_name": field, "value": value},
    )
    call = mutation_calls(boundary)[0]
    assert call[:2] == ["project", "item-edit"]
    assert call[call.index("--project-id") + 1] == PROJECT["id"]
    assert call[call.index("--id") + 1] == ITEM["id"]
    assert flag in call
    assert result["value"] == value


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("Status", "fixture-done", "invalid_option"),
        ("Status", "Unknown", "invalid_option"),
        ("Due", "2026-02-29", "invalid_arguments"),
        ("Due", "2026-9-12", "invalid_arguments"),
        ("Due", 123, "invalid_arguments"),
        ("Estimate", "3", "invalid_arguments"),
        ("Notes", 3, "invalid_arguments"),
        ("Notes", "", "invalid_arguments"),
        ("Missing", "x", "invalid_field"),
        ("Title", "new title", "unsupported_field"),
        ("Title", None, "unsupported_field"),
    ],
)
def test_rejects_wrong_field_types_without_mutations(boundary, field, value, code):
    with pytest.raises(GitHubToolError) as caught:
        projects.execute(
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": field, "value": value},
        )
    assert caught.value.code == code
    assert not mutation_calls(boundary)


@pytest.mark.parametrize("duplicate_option", [False, True])
def test_ambiguous_field_or_option_names_are_rejected(boundary, duplicate_option):
    if duplicate_option:
        boundary["fields"][0]["options"].append({"id": "other", "name": "DONE"})
    else:
        boundary["fields"].append({"id": "other", "name": "STATUS", "dataType": "TEXT"})
    with pytest.raises(GitHubToolError):
        projects.execute(
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Status", "value": "Done"},
        )
    assert not mutation_calls(boundary)


@pytest.mark.parametrize("archived", [True, False])
def test_archive_restore_supports_already_archived_members(boundary, archived):
    boundary["item"]["isArchived"] = True
    result = projects.execute(
        "archive_project_item", {"item_id": ITEM["id"], "archived": archived}
    )
    call = mutation_calls(boundary)[0]
    assert call[:3] == ["project", "item-archive", "73"]
    assert ("--undo" in call) is (not archived)
    assert result["archived"] is archived


@pytest.mark.parametrize("kind", ["issues", "pull"])
def test_add_existing_chatty_url(boundary, kind):
    url = f"https://github.com/vaishnavJa/Chatty/{kind}/42"
    result = projects.execute("add_project_item", {"url": url})
    assert result["id"] == ITEM["id"]
    assert mutation_calls(boundary)[0] == [
        "project",
        "item-add",
        "73",
        "--owner",
        "fixture-owner",
        "--format",
        "json",
        "--url=" + url,
    ]


def test_remove_deletes_only_project_membership(boundary):
    result = projects.execute("remove_project_item", {"item_id": ITEM["id"]})
    assert mutation_calls(boundary)[0][:2] == ["project", "item-delete"]
    assert result == {
        "item_id": ITEM["id"],
        "removed_from_project": True,
        "repository_issue_deleted": False,
    }


def test_update_details_uses_private_json_and_preserves_clears_and_literals(boundary):
    literal = "--visibility=PUBLIC\n$(whoami) `id`\n日本語"
    result = projects.execute(
        "update_project_details",
        {"title": literal, "description": "", "readme": literal},
    )
    payload = boundary["payloads"][0]
    assert payload["query"] == projects._DETAILS_MUTATION
    assert payload["variables"]["input"] == {
        "projectId": PROJECT["id"],
        "title": literal,
        "shortDescription": "",
        "readme": literal,
    }
    assert result["shortDescription"] == ""
    assert all(not path.exists() for path in boundary["paths"])


def test_details_tempfile_preflight_failure_is_certain(boundary, monkeypatch):
    def fail(**kwargs):
        raise OSError("credential-sensitive diagnostic")

    monkeypatch.setattr(projects.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(GitHubToolError) as caught:
        projects.execute("update_project_details", {"readme": "x"})
    assert caught.value.code == "local_io_error"
    assert caught.value.uncertain is False
    assert not mutation_calls(boundary)


@pytest.mark.parametrize("response", [{}, {"id": "PVTI_other"}, []])
def test_unconfirmed_mutations_are_uncertain(boundary, response):
    boundary["write_response"] = response
    with pytest.raises(GitHubToolError) as caught:
        projects.execute("remove_project_item", {"item_id": ITEM["id"]})
    assert caught.value.uncertain is True
    assert len(mutation_calls(boundary)) == 1


def test_write_timeout_is_uncertain_without_retry(boundary):
    boundary["write_error"] = subprocess.TimeoutExpired(["gh"], 30)
    with pytest.raises(GitHubToolError) as caught:
        projects.execute(
            "archive_project_item", {"item_id": ITEM["id"], "archived": True}
        )
    assert caught.value.code == "timeout"
    assert caught.value.uncertain is True
    assert len(mutation_calls(boundary)) == 1


def test_raw_cli_diagnostics_never_escape(boundary):
    boundary["write_stderr"] = "secret-token-sensitive and private project details"
    with pytest.raises(GitHubToolError) as caught:
        projects.execute("remove_project_item", {"item_id": ITEM["id"]})
    assert "secret" not in str(caught.value)
    assert caught.value.uncertain is True


def test_graphql_errors_are_private_and_block_mutation(boundary):
    boundary["fields_response"] = {
        "errors": [{"message": "sensitive private project identity"}]
    }
    with pytest.raises(GitHubToolError) as caught:
        projects.execute(
            "update_project_item",
            {"item_id": ITEM["id"], "field_name": "Status", "value": "Done"},
        )
    assert caught.value.code == "project_access_error"
    assert "sensitive" not in str(caught.value)
    assert not mutation_calls(boundary)


def test_environment_secrets_are_not_in_schema_or_arguments(boundary, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-secret")
    projects.execute("get_project", {})
    assert "fixture-secret" not in json.dumps(boundary["calls"])
    assert os.environ["CHATTY_PROJECT_OWNER"] not in json.dumps(projects.TOOL_SCHEMAS)


def test_field_pagination_uses_server_cursors_and_collects_all_fields(
    boundary, monkeypatch
):
    calls = []

    def graphql(query, **variables):
        calls.append(variables)
        page = len(calls)
        return {
            "node": {
                "id": PROJECT["id"],
                "fields": {
                    "nodes": [FIELDS[page - 1]],
                    "totalCount": 2,
                    "pageInfo": {
                        "hasNextPage": page == 1,
                        "endCursor": "fixture-cursor" if page == 1 else None,
                    },
                },
            }
        }

    monkeypatch.setattr(projects, "_graphql", graphql)
    result = projects.execute("list_project_fields", {})
    assert result["fields"] == FIELDS[:2]
    assert calls == [
        {"project": PROJECT["id"]},
        {"project": PROJECT["id"], "after": "fixture-cursor"},
    ]


def test_repeating_pagination_cursor_fails_without_guessing_fields(boundary):
    boundary["fields_response"] = {
        "data": {
            "node": {
                "id": PROJECT["id"],
                "fields": {
                    "nodes": [FIELDS[0]],
                    "totalCount": 3,
                    "pageInfo": {"hasNextPage": True, "endCursor": "same-cursor"},
                },
            }
        }
    }
    with pytest.raises(GitHubToolError) as caught:
        projects.execute("list_project_fields", {})
    assert caught.value.code == "invalid_response"
    assert len(boundary["calls"]) == 3
