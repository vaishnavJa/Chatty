"""Exercise real transport with subprocess fixtures; never write to GitHub."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from chatty.integrations.github import writes
from chatty.integrations.github.transport import GitHubToolError


class CreateIssueTests(unittest.TestCase):
    def setUp(self):
        boundary = patch("chatty.integrations.github.transport.subprocess.run")
        self.run = boundary.start()
        self.addCleanup(boundary.stop)

    def test_local_preflight_failure_does_not_attempt_write(self):
        run = self.run
        with patch.object(
            writes.tempfile, "NamedTemporaryFile", side_effect=OSError("fixture")
        ):
            with self.assertRaises(GitHubToolError) as caught:
                writes.create_issue("title", "body")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.code, "local_io_error")
        run.assert_not_called()

    def test_cli_start_failure_preserves_certain_preflight_error(self):
        for failure, code in [
            (FileNotFoundError(), "gh_unavailable"),
            (PermissionError(), "permission_denied"),
        ]:
            with self.subTest(code=code):
                self.run.reset_mock()
                self.run.side_effect = failure
                with self.assertRaises(GitHubToolError) as caught:
                    writes.create_issue("title", "body")
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(caught.exception.uncertain)
                self.assertEqual(self.run.call_count, 1)
                args = self.run.call_args.args[0]
                self.assertFalse(Path(args[args.index("--body-file") + 1]).exists())

    def test_timeout_removes_body_and_preserves_uncertainty(self):
        paths = []

        def timeout(args, **kwargs):
            paths.append(Path(args[args.index("--body-file") + 1]))
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        self.run.side_effect = timeout
        with self.assertRaises(GitHubToolError) as caught:
            writes.create_issue("title", "body")
        self.assertEqual(
            caught.exception.as_dict(),
            {
                "code": "timeout",
                "message": "GitHub request timed out. Check its outcome before retrying.",
                "uncertain": True,
            },
        )
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())

    def test_rejects_invalid_input_before_transport(self):
        run = self.run
        for title, body in [
            ("", ""),
            (" \t\n", ""),
            ("x" * 257, ""),
            (True, ""),
            (1, ""),
            ("ok", None),
            ("ok", "x" * 65537),
            ("bad\0title", ""),
            ("ok", "\ud800"),
        ]:
            with self.subTest(title=repr(title)[:30], body=repr(body)[:30]):
                with self.assertRaises(GitHubToolError) as caught:
                    writes.create_issue(title, body)
                self.assertEqual(caught.exception.code, "invalid_arguments")
                self.assertFalse(caught.exception.uncertain)
        run.assert_not_called()

    def test_nonzero_error_is_uncertain_and_file_is_removed_without_retry(self):
        paths = []

        def fail(args, **kwargs):
            paths.append(Path(args[args.index("--body-file") + 1]))
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="fixture failure"
            )

        self.run.side_effect = fail
        with self.assertRaises(GitHubToolError) as caught:
            writes.create_issue("title", "body")
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(caught.exception.code, "github_error")
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())

    def test_rejects_unconfirmed_output_as_uncertain(self):
        for output in [
            "",
            "created!",
            "https://github.com/other/repo/issues/42",
            "https://github.com/vaishnavJa/Chatty/pull/42",
            "https://github.com/vaishnavJa/Chatty/issues/0",
            "https://github.com/vaishnavJa/Chatty/issues/01",
            "https://github.com/vaishnavJa/Chatty/issues/42?x=1",
            "https://github.com/vaishnavJa/Chatty/issues/42\nextra",
        ]:
            with self.subTest(output=output):
                run = self.run
                run.reset_mock()
                run.return_value = subprocess.CompletedProcess([], 0, stdout=output)
                with self.assertRaises(GitHubToolError) as caught:
                    writes.create_issue("title", "body")
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(run.call_count, 1)

    def test_accepts_inclusive_bounds_and_empty_body(self):
        for title, body in [("x", ""), ("🐍" * 256, "あ" * 65536)]:
            with self.subTest(lengths=(len(title), len(body))):
                self.run.return_value = subprocess.CompletedProcess(
                    [], 0, stdout="https://github.com/vaishnavJa/Chatty/issues/1"
                )
                self.assertEqual(writes.create_issue(title, body)["number"], 1)

    def test_preserves_literal_text_and_removes_private_body_file(self):
        title = "--repo=evil/repo 日本語 $(touch nope); `whoami`"
        body = "Unicode: café 🐍\r\nsecond line\n$HOME; `id`\n"
        paths = []

        def run_gh(args, **kwargs):
            self.assertEqual(args[0], "gh")
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["env"]["GH_HOST"], "github.com")
            args = args[1:]
            self.assertEqual(
                args[:4], ["issue", "create", "--repo", "vaishnavJa/Chatty"]
            )
            self.assertIn("--title=" + title, args)
            path = Path(args[args.index("--body-file") + 1])
            paths.append(path)
            self.assertEqual(path.read_bytes(), body.encode("utf-8"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(
                args, 0, stdout="https://github.com/vaishnavJa/Chatty/issues/42\n"
            )

        self.run.side_effect = run_gh
        result = writes.create_issue(title, body)
        self.assertEqual(
            result,
            {"number": 42, "url": "https://github.com/vaishnavJa/Chatty/issues/42"},
        )
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
