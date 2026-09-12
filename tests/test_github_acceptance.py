"""Offline acceptance contracts; only the subprocess boundary is replaced."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatty.agents.tools import TOOL_SCHEMAS, execute_call, execute_tool
from chatty.integrations.github.dedup import CallLedger

REPOSITORY = "vaishnavJa/Chatty"
ISSUE_URL = "https://github.com/vaishnavJa/Chatty/issues/42"


class GitHubAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger_path = Path(self.directory.name) / "calls.sqlite3"
        self.ledger = CallLedger(self.ledger_path)
        boundary = patch("chatty.integrations.github.transport.subprocess.run")
        self.process = boundary.start()
        self.addCleanup(boundary.stop)
        self.process.return_value = subprocess.CompletedProcess(["gh"], 0, "[]", "")

    def assert_error(self, result, *, uncertain=None):
        self.assertIs(result["ok"], False)
        self.assertEqual(set(result["error"]), {"code", "message", "uncertain"})
        self.assertIsInstance(result["error"]["code"], str)
        self.assertTrue(result["error"]["message"])
        self.assertIs(type(result["error"]["uncertain"]), bool)
        if uncertain is not None:
            self.assertIs(result["error"]["uncertain"], uncertain)

    def call_create(self, *, authorized=True, title="Fixture issue", ledger=None):
        response = execute_call(
            "session-acceptance",
            "call-create",
            "create_issue",
            {"title": title, "body": "Fixture body"},
            explicit_user_request=authorized,
            ledger=ledger if ledger is not None else self.ledger,
        )
        self.assertEqual(set(response), {"call_id", "output"})
        self.assertEqual(response["call_id"], "call-create")
        self.assertIsInstance(response["output"], str)
        return json.loads(response["output"])

    def test_schemas_expose_only_four_bounded_tools(self):
        schemas = {schema["name"]: schema for schema in TOOL_SCHEMAS}
        self.assertEqual(len(TOOL_SCHEMAS), 4)
        self.assertEqual(
            set(schemas),
            {
                "list_recent_commits",
                "list_open_pull_requests",
                "list_open_issues",
                "create_issue",
            },
        )
        for name, schema in schemas.items():
            with self.subTest(name=name):
                self.assertEqual(schema["type"], "function")
                self.assertTrue(schema["description"])
                parameters = schema["parameters"]
                self.assertEqual(parameters["type"], "object")
                self.assertIs(parameters["additionalProperties"], False)
                expected = {"title", "body"} if name == "create_issue" else {"limit"}
                self.assertEqual(set(parameters["properties"]), expected)

    def test_empty_reads_are_honest_and_repo_fixed(self):
        for name in (
            "list_recent_commits",
            "list_open_pull_requests",
            "list_open_issues",
        ):
            with self.subTest(name=name):
                result = execute_tool(name, {})
                self.assertEqual(
                    result, {"ok": True, "repository": REPOSITORY, "data": []}
                )
                args, kwargs = self.process.call_args
                self.assertIsInstance(args[0], list)
                self.assertEqual(Path(args[0][0]).name, "gh")
                self.assertIn(REPOSITORY, " ".join(args[0]))
                self.assertFalse(kwargs.get("shell", False))
                self.assertGreater(kwargs["timeout"], 0)

    def test_invalid_arguments_never_reach_github(self):
        cases = [
            ("unknown", {}),
            ("list_open_issues", {"repository": "other/repo"}),
            ("list_open_issues", {"repo": REPOSITORY}),
            ("list_open_issues", {"limit": True}),
            ("list_open_issues", {"limit": "10"}),
            ("list_open_issues", {"limit": 0}),
            ("list_open_issues", {"limit": 101}),
            ("create_issue", {"title": " ", "body": ""}),
            ("create_issue", {"title": "x" * 257, "body": ""}),
            ("create_issue", {"title": "x", "body": "x" * 65537}),
            ("create_issue", {"title": "x", "body": "", "explicit_user_request": True}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, fields=list(arguments)):
                self.assert_error(
                    execute_tool(name, arguments, explicit_user_request=True)
                )
        self.process.assert_not_called()

    def test_read_results_preserve_source_evidence(self):
        timestamp = "2026-09-01T12:00:00Z"
        sha = "1234567890abcdef1234567890abcdef12345678"
        cases = [
            (
                "list_recent_commits",
                {
                    "sha": sha,
                    "html_url": f"https://github.com/{REPOSITORY}/commit/{sha}",
                    "author": {"login": "fixture-author"},
                    "commit": {
                        "message": "Fixture commit",
                        "author": {
                            "name": "fixture-author",
                            "date": timestamp,
                        },
                        "committer": {"date": timestamp},
                    },
                },
                "sha",
                sha,
            ),
            (
                "list_open_pull_requests",
                {
                    "number": 41,
                    "title": "Fixture PR",
                    "url": f"https://github.com/{REPOSITORY}/pull/41",
                    "html_url": f"https://github.com/{REPOSITORY}/pull/41",
                    "author": {"login": "fixture-author"},
                    "user": {"login": "fixture-author"},
                    "createdAt": timestamp,
                    "created_at": timestamp,
                },
                "number",
                41,
            ),
            (
                "list_open_issues",
                {
                    "number": 42,
                    "title": "Fixture issue",
                    "url": ISSUE_URL,
                    "html_url": ISSUE_URL,
                    "author": {"login": "fixture-author"},
                    "user": {"login": "fixture-author"},
                    "createdAt": timestamp,
                    "created_at": timestamp,
                },
                "number",
                42,
            ),
        ]
        for name, fixture, identifier, expected in cases:
            with self.subTest(name=name):
                self.process.return_value = subprocess.CompletedProcess(
                    ["gh"], 0, json.dumps([fixture]), ""
                )
                result = execute_tool(name, {"limit": 1})
                self.assertIs(result["ok"], True)
                self.assertEqual(result["repository"], REPOSITORY)
                self.assertEqual(len(result["data"]), 1)
                record = result["data"][0]
                self.assertEqual(record[identifier], expected)
                self.assertEqual(record["url"], fixture["html_url"])
                self.assertEqual(record["author"], "fixture-author")
                self.assertEqual(record["created_at"], timestamp)
                if identifier == "number":
                    self.assertEqual(record["title"], fixture["title"])

    def test_denied_call_does_not_reserve_key(self):
        self.assert_error(self.call_create(authorized=False), uncertain=False)
        self.process.assert_not_called()
        self.process.return_value = subprocess.CompletedProcess(
            ["gh"], 0, ISSUE_URL + "\n", ""
        )
        self.assertEqual(
            self.call_create(),
            {
                "ok": True,
                "repository": REPOSITORY,
                "data": {"number": 42, "url": ISSUE_URL},
            },
        )

    def test_completed_create_survives_ledger_reopen_and_rejects_conflict(self):
        self.process.return_value = subprocess.CompletedProcess(
            ["gh"], 0, ISSUE_URL + "\n", ""
        )
        first = self.call_create()
        self.assertIs(first["ok"], True)
        self.assertEqual(self.call_create(ledger=CallLedger(self.ledger_path)), first)
        self.assert_error(self.call_create(title="Different payload"))
        self.assertEqual(self.process.call_count, 1)

    def test_timeout_is_cached_as_uncertain_without_retry(self):
        self.process.side_effect = subprocess.TimeoutExpired(["gh"], 30)
        first = self.call_create()
        self.assert_error(first, uncertain=True)
        self.assertEqual(self.call_create(ledger=CallLedger(self.ledger_path)), first)
        self.assertEqual(self.process.call_count, 1)

    def test_duplicate_delivery_during_write_returns_pending(self):
        pending = []

        def create_fixture(args, **kwargs):
            pending.append(self.call_create(ledger=CallLedger(self.ledger_path)))
            return subprocess.CompletedProcess(args, 0, ISSUE_URL + "\n", "")

        self.process.side_effect = create_fixture
        completed = self.call_create()
        self.assertIs(completed["ok"], True)
        self.assertEqual(len(pending), 1)
        self.assert_error(pending[0], uncertain=True)
        self.assertEqual(pending[0]["error"]["code"], "call_pending")
        self.assertEqual(self.process.call_count, 1)
        self.assertEqual(self.call_create(), completed)
        self.assertEqual(self.process.call_count, 1)

    def test_multiline_shell_metacharacters_are_literal_file_contents(self):
        title = "Fixture ; $(echo nope) `echo nope`"
        body = "First line\n$(echo nope); & | < >\n日本語\n"
        captured_paths = []

        def create_fixture(args, **kwargs):
            self.assertIsInstance(args, list)
            self.assertFalse(kwargs.get("shell", False))
            self.assertIn("--title=" + title, args)
            path = Path(args[args.index("--body-file") + 1])
            captured_paths.append(path)
            self.assertEqual(path.read_text(encoding="utf-8"), body)
            self.assertNotIn(body, args)
            return subprocess.CompletedProcess(args, 0, ISSUE_URL + "\n", "")

        self.process.side_effect = create_fixture
        result = execute_tool(
            "create_issue", {"title": title, "body": body}, explicit_user_request=True
        )
        self.assertEqual(
            result,
            {
                "ok": True,
                "repository": REPOSITORY,
                "data": {"number": 42, "url": ISSUE_URL},
            },
        )
        self.assertEqual(len(captured_paths), 1)
        self.assertFalse(captured_paths[0].exists())

    def test_pending_reservation_is_visible_to_another_ledger(self):
        payload = {"name": "create_issue", "args": {"title": "Fixture", "body": ""}}
        nested = []
        success = {
            "ok": True,
            "repository": REPOSITORY,
            "data": {"number": 42, "url": ISSUE_URL},
        }

        def operation():
            nested.append(
                CallLedger(self.ledger_path).run(
                    "session",
                    "pending",
                    payload,
                    lambda: self.fail("Pending operation must never run twice"),
                )
            )
            return success

        self.assertEqual(
            self.ledger.run("session", "pending", payload, operation), success
        )
        self.assertEqual(len(nested), 1)
        self.assert_error(nested[0], uncertain=True)
        self.process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
