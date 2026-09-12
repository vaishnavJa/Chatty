"""Dispatcher unit contracts with scoped fixtures for separately owned modules.

These fixtures do not exercise the transport or SQLite ledger implementation.
They never leave replacement modules or import paths installed after a test.
"""

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_tools():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "github_tools_under_test", root / "src/chatty/agents/tools.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(root / "src"), *sys.path]):
        spec.loader.exec_module(module)
    return module


class FixtureGitHubToolError(Exception):
    def __init__(self, code, message, *, uncertain=False):
        self.code, self.message, self.uncertain = code, message, uncertain

    def as_dict(self):
        return {"code": self.code, "message": self.message, "uncertain": self.uncertain}


class FixtureLedger:
    def __init__(self, path=None, result=None):
        self.path = path
        self.result = result
        self.reservations = []

    def run(self, session_id, call_id, payload, operation):
        self.reservations.append((session_id, call_id, payload))
        if self.result is not None:
            return self.result
        return operation()


def dependency_fixtures():
    names = (
        "chatty",
        "chatty.integrations",
        "chatty.integrations.github",
        "chatty.integrations.github.transport",
        "chatty.integrations.github.reads",
        "chatty.integrations.github.writes",
        "chatty.integrations.github.dedup",
    )
    modules = {name: types.ModuleType(name) for name in names}
    for name in names:
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(modules[parent], child, modules[name])
    prefix = "chatty.integrations.github."
    modules[prefix + "transport"].GitHubToolError = FixtureGitHubToolError
    modules[prefix + "transport"].REPOSITORY = "vaishnavJa/Chatty"
    modules[prefix + "dedup"].CallLedger = FixtureLedger
    return modules


class DispatcherTests(unittest.TestCase):
    def test_unknown_tool_is_structured_failure(self):
        tools = load_tools()
        result = tools.execute_tool("shell", {"command": "echo no"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown_tool")
        self.assertFalse(result["error"]["uncertain"])

    def test_create_without_ledger_fails_closed(self):
        tools = load_tools()
        with patch.dict(os.environ, {}, clear=True):
            response = tools.execute_call(
                "session",
                "call",
                "create_issue",
                {"title": "Title", "body": ""},
                explicit_user_request=True,
            )
        self.assertEqual(
            json.loads(response["output"])["error"]["code"], "ledger_not_configured"
        )

    def test_rejects_invalid_inputs_without_loading_dependencies(self):
        tools = load_tools()
        cases = [
            ("list_open_issues", {"limit": True}),
            ("list_open_issues", {"limit": 0}),
            ("list_open_issues", {"limit": 101}),
            ("list_open_issues", {"limit": 1.0}),
            ("list_open_issues", {"limit": "10"}),
            ("list_open_issues", {"repository": "evil/repo"}),
            ("list_open_issues", {"repo": "vaishnavJa/Chatty"}),
            ("list_open_issues", {"explicit_user_request": True}),
            ("list_open_issues", []),
            ("create_issue", {"title": " ", "body": ""}),
            ("create_issue", {"title": "x" * 257, "body": ""}),
            ("create_issue", {"title": "x", "body": "x" * 65537}),
            ("create_issue", {"title": True, "body": ""}),
            ("create_issue", {"title": "x", "body": None}),
            ("create_issue", {"title": "x"}),
            ("create_issue", {"title": "x", "body": "", "explicit_user_request": True}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=str(arguments)[:100]):
                result = tools.execute_tool(name, arguments, explicit_user_request=True)
                self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_write_authorization_requires_literal_true_before_reservation(self):
        tools = load_tools()
        for authorization in (False, None, 0, 1, "true", [], {"trusted": True}):
            with self.subTest(authorization=authorization):
                ledger = FixtureLedger()
                response = tools.execute_call(
                    "s",
                    "c",
                    "create_issue",
                    {"title": "title", "body": ""},
                    explicit_user_request=authorization,
                    ledger=ledger,
                )
                self.assertEqual(
                    json.loads(response["output"])["error"]["code"],
                    "authorization_required",
                )
                self.assertEqual(ledger.reservations, [])

    def test_exact_four_schemas_with_no_trust_or_repository_arguments(self):
        schemas = load_tools().TOOL_SCHEMAS
        self.assertEqual(
            {item["name"] for item in schemas},
            {
                "list_recent_commits",
                "list_open_pull_requests",
                "list_open_issues",
                "create_issue",
            },
        )
        self.assertEqual(len(schemas), 4)
        for schema in schemas:
            with self.subTest(name=schema["name"]):
                self.assertEqual(schema["type"], "function")
                self.assertFalse(schema["parameters"]["additionalProperties"])
                expected = (
                    {"title", "body"} if schema["name"] == "create_issue" else {"limit"}
                )
                self.assertEqual(set(schema["parameters"]["properties"]), expected)


class DurableAdapterTests(unittest.TestCase):
    """Use the real borrowed ledger/transport; only the write is a fixture."""

    def setUp(self):
        self.tools = load_tools()
        root = Path(__file__).resolve().parents[1]
        with patch.object(sys, "path", [str(root / "src"), *sys.path]):
            from chatty.integrations.github.dedup import CallLedger
        self.ledger_type = CallLedger
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "calls.sqlite3")
        self.arguments = {"title": "fixture", "body": ""}
        self.writes = types.ModuleType("chatty.integrations.github.writes")
        scope = patch.dict(sys.modules, {self.writes.__name__: self.writes})
        scope.start()
        self.addCleanup(scope.stop)

    def call(self, arguments=None):
        return self.tools.execute_call(
            "session",
            "call",
            "create_issue",
            self.arguments if arguments is None else arguments,
            explicit_user_request=True,
            ledger=self.ledger_type(self.path),
        )

    def test_new_ledger_instance_replays_success_and_rejects_conflict(self):
        writes = []

        def create(title, body):
            writes.append(title)
            return {
                "number": 42,
                "url": "https://github.com/vaishnavJa/Chatty/issues/42",
            }

        self.writes.create_issue = create
        first = self.call()
        self.assertTrue(json.loads(first["output"])["ok"])
        self.assertEqual(self.call(), first)
        conflict = self.call({"title": "changed", "body": ""})
        self.assertEqual(
            json.loads(conflict["output"])["error"]["code"], "call_conflict"
        )
        self.assertEqual(writes, ["fixture"])

    def test_uncertain_error_is_cached_without_retry(self):
        writes = []

        def create(title, body):
            writes.append(title)
            raise self.tools.GitHubToolError(
                "timeout", "Outcome unknown.", uncertain=True
            )

        self.writes.create_issue = create
        first = self.call()
        self.assertTrue(json.loads(first["output"])["error"]["uncertain"])
        self.assertEqual(self.call(), first)
        self.assertEqual(writes, ["fixture"])

    def test_interrupted_reservation_remains_pending(self):
        def interrupt():
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.ledger_type(self.path).run(
                "session",
                "call",
                {"name": "create_issue", "arguments": self.arguments},
                interrupt,
            )
        response = self.call()
        self.assertEqual(
            json.loads(response["output"])["error"]["code"], "call_pending"
        )
        self.assertTrue(json.loads(response["output"])["error"]["uncertain"])


class FixtureDispatchTests(unittest.TestCase):
    def setUp(self):
        self.modules = dependency_fixtures()
        self.scope = patch.dict(sys.modules, self.modules)
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.tools = load_tools()
        self.reads = self.modules["chatty.integrations.github.reads"]
        self.writes = self.modules["chatty.integrations.github.writes"]

    def test_reads_preserve_evidence_and_default_and_boundary_limits(self):
        evidence = [
            {
                "url": "https://github.com/vaishnavJa/Chatty/commit/abc",
                "sha": "abc",
                "author": "fixture-author",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        for name in (
            "list_recent_commits",
            "list_open_pull_requests",
            "list_open_issues",
        ):
            for arguments, expected_limit in (
                ({}, 10),
                ({"limit": 1}, 1),
                ({"limit": 100}, 100),
            ):
                with self.subTest(name=name, arguments=arguments):

                    def read(*, limit, expected_limit=expected_limit):
                        self.assertEqual(limit, expected_limit)
                        return evidence

                    setattr(self.reads, name, read)
                    result = self.tools.execute_tool(name, arguments)
                    self.assertEqual(
                        result,
                        {
                            "ok": True,
                            "repository": "vaishnavJa/Chatty",
                            "data": evidence,
                        },
                    )

    def test_call_returns_json_empty_read_without_a_ledger(self):
        self.reads.list_open_issues = lambda *, limit: []
        response = self.tools.execute_call("s", "c", "list_open_issues", {})
        self.assertEqual(response["call_id"], "c")
        self.assertEqual(
            json.loads(response["output"]),
            {"ok": True, "repository": "vaishnavJa/Chatty", "data": []},
        )

    def test_create_preserves_literal_data_and_reserves_full_payload(self):
        arguments = {
            "title": "$(echo nope); 'quoted'",
            "body": "line one\n`echo nope`\n雪",
        }
        created = {
            "number": 42,
            "url": "https://github.com/vaishnavJa/Chatty/issues/42",
        }

        def write(title, body):
            self.assertEqual({"title": title, "body": body}, arguments)
            return created

        self.writes.create_issue = write
        ledger = FixtureLedger()
        response = self.tools.execute_call(
            "s",
            "c",
            "create_issue",
            arguments,
            explicit_user_request=True,
            ledger=ledger,
        )
        self.assertEqual(
            json.loads(response["output"]),
            {"ok": True, "repository": "vaishnavJa/Chatty", "data": created},
        )
        self.assertEqual(
            ledger.reservations,
            [("s", "c", {"name": "create_issue", "arguments": arguments})],
        )

    def test_maximum_create_lengths_are_accepted(self):
        self.writes.create_issue = lambda title, body: {
            "number": 42,
            "url": "fixture-url",
        }
        result = self.tools.execute_tool(
            "create_issue",
            {"title": "x" * 256, "body": "x" * 65536},
            explicit_user_request=True,
        )
        self.assertTrue(result["ok"])

    def test_known_errors_preserve_uncertainty(self):
        def write(title, body):
            raise FixtureGitHubToolError(
                "timeout", "Creation outcome is unknown.", uncertain=True
            )

        self.writes.create_issue = write
        response = self.tools.execute_call(
            "s",
            "c",
            "create_issue",
            {"title": "x", "body": ""},
            explicit_user_request=True,
            ledger=FixtureLedger(),
        )
        self.assertEqual(
            json.loads(response["output"]),
            {
                "ok": False,
                "error": {
                    "code": "timeout",
                    "message": "Creation outcome is unknown.",
                    "uncertain": True,
                },
            },
        )

    def test_unexpected_error_does_not_expose_exception_text(self):
        def write(title, body):
            raise RuntimeError("fixture-secret-do-not-display")

        self.writes.create_issue = write
        result = self.tools.execute_tool(
            "create_issue", {"title": "x", "body": ""}, explicit_user_request=True
        )
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertTrue(result["error"]["uncertain"])

    def test_pending_cached_and_conflict_results_pass_through_without_a_write(self):
        for result in (
            {
                "ok": True,
                "repository": "vaishnavJa/Chatty",
                "data": {"number": 42, "url": "fixture-url"},
            },
            {
                "ok": False,
                "error": {"code": "pending", "message": "Pending", "uncertain": True},
            },
            {
                "ok": False,
                "error": {
                    "code": "conflict",
                    "message": "Conflict",
                    "uncertain": False,
                },
            },
        ):
            with self.subTest(result=result):
                response = self.tools.execute_call(
                    "s",
                    "c",
                    "create_issue",
                    {"title": "x", "body": ""},
                    explicit_user_request=True,
                    ledger=FixtureLedger(result=result),
                )
                self.assertEqual(json.loads(response["output"]), result)

    def test_environment_selects_ledger_and_memory_is_rejected(self):
        constructed = []

        def ledger_factory(path):
            constructed.append(path)
            return FixtureLedger(
                result={"ok": True, "repository": "vaishnavJa/Chatty", "data": {}}
            )

        self.modules["chatty.integrations.github.dedup"].CallLedger = ledger_factory
        with patch.dict(
            os.environ,
            {"CHATTY_GITHUB_LEDGER_PATH": "/configured/persistent/calls.sqlite3"},
        ):
            response = self.tools.execute_call(
                "s",
                "c",
                "create_issue",
                {"title": "x", "body": ""},
                explicit_user_request=True,
            )
        self.assertTrue(json.loads(response["output"])["ok"])
        self.assertEqual(constructed, ["/configured/persistent/calls.sqlite3"])
        with patch.dict(os.environ, {"CHATTY_GITHUB_LEDGER_PATH": ":memory:"}):
            response = self.tools.execute_call(
                "s",
                "c",
                "create_issue",
                {"title": "x", "body": ""},
                explicit_user_request=True,
            )
        self.assertEqual(
            json.loads(response["output"])["error"]["code"], "ledger_not_configured"
        )

    def test_invalid_call_identifiers_never_reserve(self):
        for session_id, call_id in (("", "c"), ("s", " "), (1, "c"), ("s", None)):
            with self.subTest(session_id=session_id, call_id=call_id):
                ledger = FixtureLedger()
                response = self.tools.execute_call(
                    session_id,
                    call_id,
                    "create_issue",
                    {"title": "x", "body": ""},
                    explicit_user_request=True,
                    ledger=ledger,
                )
                self.assertEqual(
                    json.loads(response["output"])["error"]["code"], "invalid_arguments"
                )
                self.assertEqual(ledger.reservations, [])
