"""Fixture tests using real GitHub modules and a mocked subprocess boundary."""

import json
import subprocess
import unittest
from unittest.mock import patch

from chatty.integrations.github import reads, transport
from chatty.integrations.github.transport import GitHubToolError


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.reads = reads
        self.cli = self.enterContext(patch.object(transport.subprocess, "run"))

    def test_empty_results_are_honest(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps([]), stderr=""
        )
        self.assertEqual(self.reads.list_recent_commits(), [])

    def test_real_transport_classifies_auth_failure(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [], 4, stdout="", stderr="authentication required"
        )
        with self.assertRaises(GitHubToolError) as caught:
            self.reads.list_open_issues()
        self.assertEqual(caught.exception.code, "auth_required")
        self.assertFalse(caught.exception.uncertain)

    def test_real_transport_rejects_invalid_json(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [], 0, stdout="invalid JSON", stderr=""
        )
        with self.assertRaises(GitHubToolError) as caught:
            self.reads.list_recent_commits()
        self.assertEqual(caught.exception.code, "invalid_json")

    def test_commit_evidence_is_normalized(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {
                        "sha": "a" * 40,
                        "html_url": "https://github.com/vaishnavJa/Chatty/commit/"
                        + "a" * 40,
                        "author": {"login": "alice"},
                        "commit": {
                            "author": {"name": "Alice", "date": "2026-09-01T12:00:00Z"},
                            "message": "Fix bug\n\nDetails",
                        },
                    }
                ]
            ),
            stderr="",
        )
        self.assertEqual(
            self.reads.list_recent_commits(1),
            [
                {
                    "sha": "a" * 40,
                    "url": "https://github.com/vaishnavJa/Chatty/commit/" + "a" * 40,
                    "author": "alice",
                    "created_at": "2026-09-01T12:00:00Z",
                    "message": "Fix bug\n\nDetails",
                }
            ],
        )

    def test_issue_and_pr_evidence_and_fixed_commands(self):
        for kind, name in (
            ("issue", "list_open_issues"),
            ("pr", "list_open_pull_requests"),
        ):
            with self.subTest(kind=kind):
                path = "issues" if kind == "issue" else "pull"
                url = f"https://github.com/vaishnavJa/Chatty/{path}/9"
                self.cli.return_value = subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "number": 9,
                                "title": "$(literal)",
                                "url": url,
                                "author": {"login": "alice"},
                                "createdAt": "2026-09-01T12:00:00Z",
                            }
                        ]
                    ),
                    stderr="",
                )
                self.assertEqual(
                    getattr(self.reads, name)(100),
                    [
                        {
                            "number": 9,
                            "title": "$(literal)",
                            "url": url,
                            "author": "alice",
                            "created_at": "2026-09-01T12:00:00Z",
                        }
                    ],
                )
                self.assertEqual(
                    self.cli.call_args.args[0][1:],
                    [
                        kind,
                        "list",
                        "--repo",
                        "vaishnavJa/Chatty",
                        "--state",
                        "open",
                        "--limit",
                        "100",
                        "--json",
                        "number,title,url,author,createdAt",
                    ],
                )

    def test_invalid_limits_never_reach_transport(self):
        for name in (
            "list_recent_commits",
            "list_open_issues",
            "list_open_pull_requests",
        ):
            for value in (0, 101, True, 1.5, "10", None, "1;echo bad"):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(GitHubToolError) as caught:
                        getattr(self.reads, name)(value)
                    self.assertEqual(caught.exception.code, "invalid_arguments")
        self.cli.assert_not_called()

    def test_malformed_responses_fail_without_partial_results(self):
        for name in (
            "list_recent_commits",
            "list_open_issues",
            "list_open_pull_requests",
        ):
            for value in (None, {}, "bad", [None], [{}], [True]):
                with self.subTest(name=name, value=value):
                    self.cli.return_value = subprocess.CompletedProcess(
                        [], 0, stdout=json.dumps(value), stderr=""
                    )
                    with self.assertRaises(GitHubToolError) as caught:
                        getattr(self.reads, name)()
                    self.assertEqual(caught.exception.code, "invalid_response")

    def test_invalid_item_fields_are_rejected(self):
        valid = {
            "number": 9,
            "title": "Title",
            "author": {"login": "alice"},
            "url": "https://github.com/vaishnavJa/Chatty/issues/9",
            "createdAt": "2026-09-01T12:00:00Z",
        }
        for key, value in (
            ("number", True),
            ("number", -1),
            ("title", " "),
            ("author", {}),
            ("createdAt", "yesterday"),
            ("createdAt", "2026-09-01"),
            ("url", "https://github.com/other/repo/issues/9"),
        ):
            with self.subTest(key=key, value=value):
                self.cli.return_value = subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps([valid, {**valid, key: value}]), stderr=""
                )
                with self.assertRaises(GitHubToolError):
                    self.reads.list_open_issues()

    def test_deleted_issue_author_is_honestly_null(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {
                        "number": 9,
                        "title": "Title",
                        "author": None,
                        "url": "https://github.com/vaishnavJa/Chatty/issues/9",
                        "createdAt": "2026-09-01T12:00:00Z",
                    }
                ]
            ),
            stderr="",
        )
        self.assertIsNone(self.reads.list_open_issues()[0]["author"])

    def test_unlinked_commit_author_uses_git_name(self):
        valid = {
            "sha": "b" * 40,
            "author": None,
            "html_url": "https://github.com/vaishnavJa/Chatty/commit/" + "b" * 40,
            "commit": {
                "author": {"name": "Local Author", "date": "2026-09-01T12:00:00Z"},
                "message": "Commit message",
            },
        }
        self.cli.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps([valid]), stderr=""
        )
        self.assertEqual(self.reads.list_recent_commits(1)[0]["author"], "Local Author")
        self.assertEqual(
            self.cli.call_args.args[0][1:],
            ["api", "--method", "GET", "repos/vaishnavJa/Chatty/commits?per_page=1"],
        )
        for key, value in (
            ("sha", "short"),
            ("commit", {}),
            ("author", {}),
            ("html_url", "https://example.com"),
        ):
            with self.subTest(key=key):
                self.cli.return_value = subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps([{**valid, key: value}]), stderr=""
                )
                with self.assertRaises(GitHubToolError):
                    self.reads.list_recent_commits()

    def test_response_cannot_exceed_requested_limit(self):
        self.cli.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps([{}, {}]), stderr=""
        )
        with self.assertRaises(GitHubToolError) as caught:
            self.reads.list_open_issues(1)
        self.assertEqual(caught.exception.code, "invalid_response")

    def test_all_reads_return_empty_and_propagate_transport_errors(self):
        for name in (
            "list_recent_commits",
            "list_open_issues",
            "list_open_pull_requests",
        ):
            with self.subTest(name=name):
                self.cli.return_value = subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps([]), stderr=""
                )
                self.assertEqual(getattr(self.reads, name)(), [])
                failure = GitHubToolError("auth", "Authentication required")
                self.cli.side_effect = failure
                with self.assertRaises(GitHubToolError) as caught:
                    getattr(self.reads, name)()
                self.assertIs(caught.exception, failure)
                self.cli.side_effect = None


if __name__ == "__main__":
    unittest.main()
