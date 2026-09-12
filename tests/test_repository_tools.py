"""Fixture-only API contract tests; no GitHub requests or mutations are made."""

import base64
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chatty.integrations.github import repository_tools as repo
from chatty.integrations.github.transport import GitHubToolError

SHA = "a" * 40
OTHER_SHA = "b" * 40
URL = "https://github.com/vaishnavJa/Chatty"
ROOT = "repos/vaishnavJa/Chatty"


def issue(number=7, *, pull=False, **kwargs):
    return {
        "number": number,
        "html_url": f"{URL}/{'pull' if pull else 'issues'}/{number}",
        "title": "Demo issue",
        "body": "Original body",
        "state": "open",
        "user": {"login": "teammate"},
        "assignees": [{"login": "example-user"}],
        "labels": [{"name": "demo"}],
        "milestone": None,
        **(
            {
                "head": {"ref": "codex/demo", "sha": SHA},
                "base": {"ref": "main"},
                "draft": True,
                "merged": False,
            }
            if pull
            else {}
        ),
        **kwargs,
    }


def comment(comment_id=44, **kwargs):
    return {
        "id": comment_id,
        "html_url": f"{URL}/issues/7#issuecomment-{comment_id}",
        "body": "Hello",
        "user": {"login": "teammate"},
        **kwargs,
    }


def repository(**kwargs):
    return {
        "full_name": "vaishnavJa/Chatty",
        "html_url": URL,
        "default_branch": "main",
        "permissions": {"push": True, "admin": False},
        **kwargs,
    }


def content(path="src/app.py", data=b"print('hi')\n", **kwargs):
    return {
        "path": path,
        "sha": SHA,
        "size": len(data),
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
        **kwargs,
    }


def branch(name="codex/demo", **kwargs):
    return {"name": name, "protected": False, "commit": {"sha": SHA}, **kwargs}


def tree(row=None):
    row = content() if row is None else row
    mode = {"file": "100644", "symlink": "120000", "directory": "040000"}.get(
        row.get("type"), "160000"
    )
    return {
        "truncated": False,
        "tree": [
            {
                "path": row["path"],
                "mode": mode,
                "sha": row["sha"],
                "size": row["size"],
                "type": "blob",
            }
        ],
    }


def file_receipt(path="src/app.py", *, delete=False):
    return {
        "content": None if delete else content(path=path, sha=OTHER_SHA),
        "commit": {"sha": OTHER_SHA, "html_url": f"{URL}/commit/{OTHER_SHA}"},
    }


class RepoToolsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = []
        self.run_patch = patch.object(repo.subprocess, "run", side_effect=self.fake_run)
        self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    def fake_run(self, args, **kwargs):
        self.assertEqual(
            args[:6], ["gh", "api", "--hostname", "github.com", "--method", args[5]]
        )
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["env"]["GH_HOST"], "github.com")
        endpoint = args[10]
        self.assertTrue(endpoint == ROOT or endpoint.startswith(ROOT + "/"))
        payload = json.loads(kwargs["input"]) if kwargs["input"] else None
        if payload is not None:
            self.assertEqual(args[-2:], ["--input", "-"])
        self.calls.append((args[5], endpoint, payload, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected GitHub request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, tuple):
            code, diagnostic = response
            kwargs["stderr"].write(diagnostic.encode())
            return subprocess.CompletedProcess(args, code)
        raw = response if isinstance(response, bytes) else json.dumps(response).encode()
        kwargs["stdout"].write(raw)
        return subprocess.CompletedProcess(args, 0)

    def assert_error(self, name, args, code, uncertain=False):
        with self.assertRaises(GitHubToolError) as caught:
            repo.execute(name, args)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.uncertain, uncertain)
        return caught.exception

    def test_schemas_have_only_function_fields_and_partition_capabilities(self):
        names = {item["name"] for item in repo.TOOL_SCHEMAS}
        self.assertEqual(len(names), 20)
        self.assertEqual(names, repo.READ_TOOLS | repo.WRITE_TOOLS)
        self.assertFalse(repo.READ_TOOLS & repo.WRITE_TOOLS)
        for schema in repo.TOOL_SCHEMAS:
            self.assertEqual(set(schema), {"type", "name", "description", "parameters"})
            self.assertFalse(schema["parameters"]["additionalProperties"])
            cap = repo.TOOL_CAPABILITIES[schema["name"]]
            self.assertEqual(
                cap["requires_approval"], schema["name"] in repo.WRITE_TOOLS
            )
            self.assertIs(type(cap["destructive"]), bool)

    def test_repository_metadata_excludes_token_and_url_extras(self):
        self.responses = [repository(temp_clone_token="secret-should-not-leak")]
        result = repo.execute("get_repository", {})
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["url"], URL)
        self.assertNotIn("secret-should-not-leak", json.dumps(result))
        self.assertEqual(self.calls[0][:3], ("GET", ROOT, None))

    def test_issue_read_and_edit_preserve_literal_json(self):
        title = 'Fix `literal` $(not-shell) \\n and "quotes"'
        body = "First line\nSecond line\n$TOKEN `echo nothing`"
        self.responses = [
            issue(),
            issue(title=title, body=body, state="closed", labels=[], assignees=[]),
        ]
        read = repo.execute("get_issue", {"issue_number": 7})
        result = repo.execute(
            "update_issue",
            {
                "issue_number": 7,
                "title": title,
                "body": body,
                "state": "closed",
                "labels": [],
                "assignees": [],
                "milestone": None,
            },
        )
        self.assertEqual(read["author"], "teammate")
        self.assertEqual(result["body"], body)
        self.assertEqual(result["state"], "closed")
        self.assertEqual(result["url"], f"{URL}/issues/7")
        self.assertEqual(
            self.calls[1][:3],
            (
                "PATCH",
                ROOT + "/issues/7",
                {
                    "title": title,
                    "body": body,
                    "state": "closed",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            ),
        )

    def test_issue_comments_list_create_edit(self):
        self.responses = [[comment()], comment(), comment(body="Changed")]
        listed = repo.execute(
            "list_issue_comments", {"issue_number": 7, "limit": 1, "page": 2}
        )
        created = repo.execute(
            "add_issue_comment", {"issue_number": 7, "body": "Hello"}
        )
        edited = repo.execute(
            "update_issue_comment", {"comment_id": 44, "body": "Changed"}
        )
        self.assertEqual(listed["items"][0]["comment_id"], 44)
        self.assertTrue(listed["has_more"])
        self.assertEqual(created["url"], f"{URL}/issues/7#issuecomment-44")
        self.assertEqual(edited["body"], "Changed")
        self.assertEqual(
            self.calls[0][1], ROOT + "/issues/7/comments?per_page=1&page=2"
        )
        self.assertEqual(
            self.calls[1][:3], ("POST", ROOT + "/issues/7/comments", {"body": "Hello"})
        )
        self.assertEqual(
            self.calls[2][:3],
            ("PATCH", ROOT + "/issues/comments/44", {"body": "Changed"}),
        )

    def test_pull_request_read_create_update(self):
        self.responses = [
            issue(pull=True),
            issue(pull=True),
            issue(pull=True, title="New title"),
        ]
        read = repo.execute("get_pull_request", {"pull_number": 7})
        created = repo.execute(
            "create_pull_request",
            {"title": "Demo", "body": "Body", "head": "codex/demo", "base": "main"},
        )
        edited = repo.execute(
            "update_pull_request",
            {"pull_number": 7, "title": "New title", "base": "staging"},
        )
        self.assertEqual(read["head_sha"], SHA)
        self.assertTrue(created["draft"])
        self.assertEqual(edited["title"], "New title")
        self.assertEqual(
            self.calls[1][:3],
            (
                "POST",
                ROOT + "/pulls",
                {
                    "title": "Demo",
                    "body": "Body",
                    "head": "codex/demo",
                    "base": "main",
                    "draft": True,
                },
            ),
        )
        self.assertEqual(
            self.calls[2][:3],
            ("PATCH", ROOT + "/pulls/7", {"title": "New title", "base": "staging"}),
        )

    def test_pull_files_omit_sensitive_old_and_new_paths(self):
        self.responses = [
            [
                {"filename": "src/app.py", "patch": "diff", "sha": SHA},
                {"filename": ".env", "patch": "secret"},
                {
                    "filename": "public.txt",
                    "previous_filename": "private-key.pem",
                    "patch": "also secret",
                },
            ]
        ]
        result = repo.execute("list_pull_request_files", {"pull_number": 7})
        self.assertEqual(result["items"][0]["patch"], "diff")
        self.assertIsNone(result["items"][1]["patch"])
        self.assertIsNone(result["items"][2]["patch"])
        self.assertEqual(result["url"], f"{URL}/pull/7/files")
        self.assertNotIn("also secret", json.dumps(result))

    def test_merge_passes_expected_sha_and_no_admin_bypass(self):
        self.responses = [{"merged": True, "sha": OTHER_SHA}]
        result = repo.execute(
            "merge_pull_request", {"pull_number": 7, "expected_head_sha": SHA}
        )
        self.assertEqual(
            self.calls[0][:3],
            ("PUT", ROOT + "/pulls/7/merge", {"sha": SHA, "merge_method": "squash"}),
        )
        self.assertTrue(result["merged"])
        self.assertEqual(result["sha"], OTHER_SHA)
        self.assert_error("merge_pull_request", {"pull_number": 7}, "invalid_arguments")
        self.assert_error(
            "merge_pull_request",
            {"pull_number": 7, "expected_head_sha": SHA, "admin": True},
            "invalid_arguments",
        )

    def test_merge_rejected_and_ambiguous_response(self):
        self.responses = [{"merged": False}, {"merged": True}]
        self.assert_error(
            "merge_pull_request",
            {"pull_number": 7, "expected_head_sha": SHA},
            "merge_blocked",
        )
        self.assert_error(
            "merge_pull_request",
            {"pull_number": 7, "expected_head_sha": SHA},
            "invalid_response",
            uncertain=True,
        )

    def test_branch_listing_create_and_delete(self):
        self.responses = [
            [branch()],
            {"sha": SHA},
            {"ref": "refs/heads/codex/new", "object": {"sha": SHA}},
            repository(),
            branch(),
            b"",
        ]
        listed = repo.execute("list_branches", {})
        created = repo.execute("create_branch", {"branch": "codex/new", "sha": SHA})
        deleted = repo.execute("delete_branch", {"branch": "codex/demo"})
        self.assertEqual(listed["items"][0]["sha"], SHA)
        self.assertEqual(created["url"], f"{URL}/tree/codex/new")
        self.assertTrue(deleted["deleted"])
        self.assertEqual(
            self.calls[2][:3],
            ("POST", ROOT + "/git/refs", {"ref": "refs/heads/codex/new", "sha": SHA}),
        )
        self.assertEqual(
            self.calls[5][:3], ("DELETE", ROOT + "/git/refs/heads/codex%2Fdemo", None)
        )

    def test_default_and_protected_branches_cannot_be_deleted(self):
        self.responses = [repository(), repository(), branch(protected=True)]
        self.assert_error("delete_branch", {"branch": "main"}, "protected_branch")
        self.assert_error("delete_branch", {"branch": "codex/demo"}, "protected_branch")
        self.assertFalse(any(call[0] == "DELETE" for call in self.calls))

    def test_read_file_decodes_unicode_at_explicit_ref(self):
        data = "Hello €\n".encode()
        self.responses = [
            tree(content(path="docs/hello world.md", data=data)),
            content(path="docs/hello world.md", data=data),
        ]
        result = repo.execute(
            "read_repository_file", {"path": "docs/hello world.md", "ref": "codex/demo"}
        )
        self.assertEqual(result["content"], data.decode())
        self.assertEqual(result["sha"], SHA)
        self.assertEqual(result["url"], f"{URL}/blob/codex/demo/docs/hello%20world.md")
        self.assertEqual(self.calls[0][1], ROOT + "/git/trees/codex%2Fdemo?recursive=1")

    def test_directory_pagination_and_sensitive_metadata_only(self):
        self.responses = [
            [
                content(path="README.md"),
                content(path=".env"),
                content(path="src/app.py"),
            ]
        ]
        result = repo.execute("list_repository_files", {"limit": 1, "page": 2})
        self.assertEqual(result["items"][0]["path"], ".env")
        self.assertTrue(result["items"][0]["sensitive"])
        self.assertNotIn("content", result["items"][0])
        self.assertTrue(result["has_more"])
        self.assertEqual(self.calls[0][1], ROOT + "/contents")

    def test_binary_large_and_symlink_content_omitted(self):
        for row in [
            content(data=b"\xff\x00"),
            content(size=65537),
            content(type="symlink", target=".env"),
        ]:
            with self.subTest(row_type=row["type"], size=row["size"]):
                self.responses = [tree(row)] + (
                    [row] if row["size"] <= 65536 and row["type"] == "file" else []
                )
                result = repo.execute("read_repository_file", {"path": "src/app.py"})
                self.assertIsNone(result["content"])
                self.assertTrue(result["content_omitted"])

    def test_malformed_base64_wrong_size_or_path_is_rejected(self):
        for row in [
            content(content="!notbase64"),
            content(size=2),
            content(sha=OTHER_SHA),
        ]:
            self.responses = [tree(content()), row]
            self.assert_error(
                "read_repository_file", {"path": "src/app.py"}, "invalid_response"
            )

    def test_existing_file_update_needs_sha_and_preserves_bytes(self):
        data = "// € and `literal`\nnew code\n"
        self.responses = [branch(), tree(), file_receipt()]
        result = repo.execute(
            "update_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/demo",
                "content": data,
                "message": "Prevent demo regression",
                "expected_sha": SHA,
            },
        )
        self.assertEqual(self.calls[0][1], ROOT + "/branches/codex%2Fdemo")
        self.assertEqual(self.calls[1][1], ROOT + "/git/trees/codex%2Fdemo?recursive=1")
        method, endpoint, payload, _ = self.calls[2]
        self.assertEqual((method, endpoint), ("PUT", ROOT + "/contents/src/app.py"))
        self.assertEqual(base64.b64decode(payload["content"]).decode(), data)
        self.assertEqual(payload["sha"], SHA)
        self.assertEqual(payload["branch"], "codex/demo")
        self.assertEqual(result["sha"], OTHER_SHA)
        self.assertFalse(result["created"])
        self.assertEqual(result["url"], f"{URL}/commit/{OTHER_SHA}")

    def test_missing_or_stale_sha_prevents_existing_file_write(self):
        for extra, code in [
            ({}, "expected_sha_required"),
            ({"expected_sha": OTHER_SHA}, "conflict"),
        ]:
            self.responses = [branch(), tree()]
            self.assert_error(
                "update_repository_file",
                {
                    "path": "src/app.py",
                    "branch": "codex/demo",
                    "content": "new",
                    "message": "Fix",
                    **extra,
                },
                code,
            )
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_new_file_requires_existing_branch_and_missing_path(self):
        self.responses = [branch(), {"truncated": False, "tree": []}, file_receipt()]
        result = repo.execute(
            "update_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/demo",
                "content": "new",
                "message": "Fix",
            },
        )
        self.assertTrue(result["created"])
        self.assertNotIn("sha", self.calls[2][2])

    def test_missing_branch_never_treated_as_missing_file(self):
        self.responses = [(1, "HTTP 404 Not Found")]
        self.assert_error(
            "update_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/missing",
                "content": "new",
                "message": "Fix",
            },
            "not_found",
        )
        self.assertEqual(len(self.calls), 1)

    def test_absent_file_with_expected_sha_never_recreated(self):
        self.responses = [branch(), {"truncated": False, "tree": []}]
        self.assert_error(
            "update_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/demo",
                "content": "new",
                "message": "Fix",
                "expected_sha": SHA,
            },
            "not_found",
        )
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_file_delete_requires_branch_sha_and_returns_commit(self):
        self.responses = [branch(), tree(), file_receipt(delete=True)]
        result = repo.execute(
            "delete_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/demo",
                "expected_sha": SHA,
                "message": "Remove obsolete fixture",
            },
        )
        self.assertTrue(result["deleted"])
        self.assertEqual(
            self.calls[2][:3],
            (
                "DELETE",
                ROOT + "/contents/src/app.py",
                {
                    "branch": "codex/demo",
                    "sha": SHA,
                    "message": "Remove obsolete fixture",
                },
            ),
        )
        self.assert_error(
            "delete_repository_file",
            {"path": "src/app.py", "branch": "codex/demo", "message": "Remove"},
            "invalid_arguments",
        )

    def test_symlink_write_never_follows_target(self):
        self.responses = [branch(), tree(content(type="symlink", target=".env"))]
        self.assert_error(
            "update_repository_file",
            {
                "path": "src/app.py",
                "branch": "codex/demo",
                "content": "new",
                "message": "Fix",
                "expected_sha": SHA,
            },
            "invalid_arguments",
        )
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_workflow_read_and_rerun(self):
        self.responses = [
            {
                "workflow_runs": [
                    {
                        "id": 123,
                        "html_url": f"{URL}/actions/runs/123",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
            b"",
        ]
        runs = repo.execute("list_workflow_runs", {"limit": 5})
        rerun = repo.execute("rerun_workflow", {"run_id": 123})
        self.assertEqual(runs["items"][0]["conclusion"], "success")
        self.assertTrue(rerun["rerun_requested"])
        self.assertEqual(
            self.calls[1][:3], ("POST", ROOT + "/actions/runs/123/rerun", None)
        )

    def test_argument_rejections_do_not_touch_cli(self):
        cases = [
            ("unknown", {}),
            ("get_issue", {"issue_number": True}),
            ("get_issue", {"issue_number": 0}),
            ("get_issue", {"issue_number": "7"}),
            ("get_issue", {"issue_number": 7, "repo": "other/repo"}),
            ("get_repository", {"owner": "other"}),
            ("update_issue", {"issue_number": 7}),
            ("update_issue", {"issue_number": 7, "title": "  "}),
            ("update_issue", {"issue_number": 7, "state": "merged"}),
            ("update_issue", {"issue_number": 7, "assignees": ["../evil"]}),
            ("list_branches", {"limit": 101}),
            ("list_branches", {"page": 0}),
            ("add_issue_comment", {"issue_number": 7, "body": "\x00"}),
            ("add_issue_comment", {"issue_number": 7, "body": "\ud800"}),
            (
                "create_pull_request",
                {"title": "Title", "body": "", "head": "main", "base": "main"},
            ),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                self.assertIsNotNone(repo.validate(name, args))
        self.assertEqual(self.calls, [])

    def test_invalid_ref_and_path_injections(self):
        for ref in [
            "../main",
            "refs/heads/../main",
            "main?x=y",
            "main#x",
            "--force",
            "main@{1}",
            "HEAD",
            "main.lock",
            "a//b",
            "a/",
            "other:main",
            "https://evil",
            "main\nPOST",
        ]:
            with self.subTest(ref=ref):
                self.assertIsNotNone(
                    repo.validate("create_branch", {"branch": ref, "sha": SHA})
                )
        for path in [
            "/etc/passwd",
            "../.env",
            "src/../.env",
            "src//file",
            "src/",
            "a?ref=other",
            "a#fragment",
            "a%2f..",
            "a\\b",
            "a\nb",
            "",
        ]:
            with self.subTest(path=path):
                self.assertIsNotNone(
                    repo.validate("read_repository_file", {"path": path})
                )
        self.assertEqual(self.calls, [])

    def test_sensitive_files_excluded_but_code_and_templates_allowed(self):
        for path in [
            ".env",
            ".env.local",
            "docs/openai.env.md",
            "certs/key.pem",
            "private-key.txt",
            ".ssh/id_ed25519",
            "config/credentials.json",
            "secrets/api.txt",
            "keys/service-account.json",
            ".git/config",
        ]:
            with self.subTest(path=path):
                failure = repo.validate("read_repository_file", {"path": path})
                self.assertIsNotNone(failure)
                self.assertEqual(failure["error"]["code"], "sensitive_path")
        for path in [
            ".env.example",
            ".env.sample",
            ".env.template",
            ".github/workflows/ci.yml",
            "src/chatty/config.py",
            "docs/my notes.md",
        ]:
            with self.subTest(path=path):
                self.assertIsNone(repo.validate("read_repository_file", {"path": path}))

    def test_credential_management_source_is_readable_and_writable(self):
        for path in [
            "src/credentials.py",
            "src/credentials.ts",
            "src/credentials.js",
            "src/credentials/provider.py",
            "src/secrets/provider.ts",
        ]:
            with self.subTest(path=path):
                self.assertIsNone(repo.validate("read_repository_file", {"path": path}))
                self.assertIsNone(
                    repo.validate(
                        "update_repository_file",
                        {
                            "path": path,
                            "branch": "codex/demo",
                            "expected_sha": SHA,
                            "content": "// implementation",
                            "message": "Fix credential selection",
                        },
                    )
                )
                self.assertIsNone(
                    repo.validate(
                        "delete_repository_file",
                        {
                            "path": path,
                            "branch": "codex/demo",
                            "expected_sha": SHA,
                            "message": "Remove obsolete module",
                        },
                    )
                )
                self.responses = [tree(content(path=path)), content(path=path)]
                result = repo.execute(
                    "read_repository_file", {"path": path, "ref": "main"}
                )
                self.assertEqual(result["content"], "print('hi')\n")
        for path in [
            "credentials.json",
            "secrets.yml",
            ".credentials/provider.py",
            ".env.py",
            "private-key.py",
            "secrets/key.pem",
            ".ssh/provider.js",
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    repo.validate("read_repository_file", {"path": path})["error"][
                        "code"
                    ],
                    "sensitive_path",
                )

    def test_utf8_byte_budget_and_unknown_write_fields(self):
        args = {
            "path": "src/app.py",
            "branch": "main",
            "content": "€" * 30000,
            "message": "Fix",
        }
        self.assertIsNotNone(repo.validate("update_repository_file", args))
        args["content"] = "okay"
        args["force"] = True
        self.assertIsNotNone(repo.validate("update_repository_file", args))
        self.assertEqual(self.calls, [])

    def test_error_sanitization_and_uncertainty(self):
        cases = [
            (401, "auth_required", False),
            (403, "permission_denied", False),
            (404, "not_found", False),
            (409, "conflict", False),
            (422, "conflict", False),
            (429, "rate_limited", False),
            (503, "github_error", True),
        ]
        for status, code, uncertain in cases:
            self.responses = [(1, f"HTTP {status} diagnostic ghp_SUPERSECRET")]
            error = self.assert_error(
                "update_issue", {"issue_number": 7, "title": "Changed"}, code, uncertain
            )
            self.assertNotIn("SUPERSECRET", str(error))
        self.responses = [
            subprocess.TimeoutExpired("secret command", 30),
            subprocess.TimeoutExpired("secret command", 30),
        ]
        self.assert_error(
            "update_issue", {"issue_number": 7, "title": "Changed"}, "timeout", True
        )
        self.assert_error("get_repository", {}, "timeout", False)

    def test_invalid_successful_write_json_and_url_are_uncertain(self):
        self.responses = [
            b"not json ghp_SUPERSECRET",
            issue(html_url="https://github.com/other/repo/issues/7"),
            comment(comment_id=45),
        ]
        error = self.assert_error(
            "update_issue",
            {"issue_number": 7, "title": "Changed"},
            "invalid_json",
            True,
        )
        self.assertNotIn("SUPERSECRET", str(error))
        self.assert_error(
            "update_issue",
            {"issue_number": 7, "title": "Changed"},
            "invalid_response",
            True,
        )
        self.assert_error(
            "update_issue_comment",
            {"comment_id": 44, "body": "Changed"},
            "invalid_response",
            True,
        )

    def test_output_bound_and_non_json_constants(self):
        self.responses = [b" " * (repo._MAX_RESPONSE_BYTES + 1), b"NaN"]
        self.assert_error("get_repository", {}, "response_too_large")
        self.assert_error("get_repository", {}, "invalid_json")

    def test_file_reads_resolve_exact_blob_without_contents_dereference(self):
        self.responses = [tree(), content()]
        result = repo.execute(
            "read_repository_file", {"path": "src/app.py", "ref": "main"}
        )
        self.assertEqual(result["content"], "print('hi')\n")
        self.assertEqual(self.calls[0][1], ROOT + "/git/trees/main?recursive=1")
        self.assertEqual(self.calls[1][1], ROOT + "/git/blobs/" + SHA)
        self.assertTrue(all("/contents" not in call[1] for call in self.calls))

    def test_truncated_trees_and_symlink_ancestor_never_fetch_content(self):
        self.responses = [
            {"truncated": True, "tree": []},
            {
                "truncated": False,
                "tree": [{"path": "src", "mode": "120000", "sha": SHA}],
            },
        ]
        self.assert_error(
            "read_repository_file", {"path": "src/app.py"}, "response_too_large"
        )
        self.assert_error(
            "read_repository_file", {"path": "src/app.py"}, "invalid_arguments"
        )
        self.assertEqual(len(self.calls), 2)

    def test_floating_point_ids_are_not_rendered_as_decimal_api_paths(self):
        self.assert_error("get_issue", {"issue_number": 7.0}, "invalid_arguments")
        self.assert_error("list_branches", {"page": 1.0}, "invalid_arguments")
        self.assert_error(
            "update_issue", {"issue_number": 7, "milestone": 2.0}, "invalid_arguments"
        )
        self.assertEqual(self.calls, [])

    def test_sha_and_login_validation_reject_trailing_newlines(self):
        self.assert_error(
            "create_branch",
            {"branch": "codex/demo", "sha": SHA + "\n"},
            "invalid_arguments",
        )
        self.assert_error(
            "merge_pull_request",
            {"pull_number": 7, "expected_head_sha": SHA + "\n"},
            "invalid_arguments",
        )
        self.assert_error(
            "update_issue",
            {"issue_number": 7, "assignees": ["teammate\n"]},
            "invalid_arguments",
        )
        self.assertEqual(self.calls, [])

    def test_cli_environment_diagnostics_disabled(self):
        self.responses = [repository()]
        with patch.dict(
            os.environ,
            {"GH_HOST": "evil.invalid", "GH_REPO": "other/repo", "GH_DEBUG": "api"},
        ):
            repo.execute("get_repository", {})
        env = self.calls[0][3]["env"]
        self.assertNotIn("GH_DEBUG", env)
        self.assertNotIn("GH_REPO", env)
        self.assertEqual(env["GH_HOST"], "github.com")
        self.assertEqual(env["GH_PROMPT_DISABLED"], "1")


if __name__ == "__main__":
    unittest.main()
