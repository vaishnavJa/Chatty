import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chatty.integrations.github.transport import GitHubToolError, run_gh, run_json


class TransportTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"GH_HOST": "example.invalid", "GH_REPO": "other/repo", "GH_DEBUG": "api"},
    )
    @patch("subprocess.run")
    def test_inherited_overrides_are_removed(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "[]", "")
        run_gh(["api", "/repos/vaishnavJa/Chatty/commits"])
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["GH_HOST"], "github.com")
        self.assertNotIn("GH_REPO", environment)
        self.assertNotIn("GH_DEBUG", environment)

    @patch("subprocess.run")
    def test_json_returns_empty_and_populated_results_honestly(self, run):
        for raw, expected in (
            ("[]", []),
            ('{"number":9}', {"number": 9}),
            ("null", None),
        ):
            with self.subTest(raw=raw):
                run.return_value = subprocess.CompletedProcess([], 0, raw, "")
                self.assertEqual(
                    run_json(["api", "/repos/vaishnavJa/Chatty/issues"]), expected
                )

    @patch("subprocess.run")
    def test_invalid_json_is_sanitized(self, run):
        for raw in ("secret fixture", "", "NaN", "Infinity"):
            with self.subTest(raw=raw):
                run.return_value = subprocess.CompletedProcess([], 0, raw, "")
                with self.assertRaises(GitHubToolError) as caught:
                    run_json(["api", "/repos/vaishnavJa/Chatty/issues"])
                self.assertEqual(caught.exception.code, "invalid_json")
                self.assertNotIn("secret fixture", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    @patch("subprocess.run")
    def test_failures_are_sanitized_and_never_retried(self, run):
        fixtures = [
            (4, "secret fixture", "auth_required"),
            (1, "HTTP 401 bad credentials secret fixture", "auth_required"),
            (1, "HTTP 403 forbidden secret fixture", "permission_denied"),
            (
                1,
                "Resource not accessible by integration secret fixture",
                "permission_denied",
            ),
            (1, "HTTP 500 secret fixture", "github_error"),
        ]
        for status, diagnostic, code in fixtures:
            with self.subTest(code=code, status=status):
                run.reset_mock()
                run.return_value = subprocess.CompletedProcess(
                    [], status, "secret fixture", diagnostic
                )
                with self.assertRaises(GitHubToolError) as caught:
                    run_gh(["issue", "create"])
                self.assertEqual(caught.exception.code, code)
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn("secret fixture", str(caught.exception.as_dict()))
                self.assertEqual(run.call_count, 1)

    @patch("subprocess.run")
    def test_os_failures_and_timeout_have_safe_errors(self, run):
        fixtures = [
            (FileNotFoundError("secret fixture"), "gh_unavailable", False),
            (PermissionError("secret fixture"), "permission_denied", False),
            (OSError("secret fixture"), "gh_unavailable", False),
            (
                subprocess.TimeoutExpired(
                    "secret fixture", 30, output="secret fixture"
                ),
                "timeout",
                True,
            ),
        ]
        for failure, code, uncertain in fixtures:
            with self.subTest(code=code, uncertain=uncertain):
                run.side_effect = failure
                with self.assertRaises(GitHubToolError) as caught:
                    run_gh(["issue", "create"])
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.uncertain, uncertain)
                self.assertNotIn("secret fixture", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    @patch("subprocess.run")
    def test_read_failure_is_not_an_uncertain_write(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "HTTP 500")
        with self.assertRaises(GitHubToolError) as caught:
            run_gh(["api", "repos/vaishnavJa/Chatty/commits"])
        self.assertFalse(caught.exception.uncertain)

    @patch("subprocess.run")
    def test_invalid_arguments_never_start_a_process(self, run):
        for args in ("issue list", [], [1], ["bad\x00argument"]):
            with self.subTest(args=args), self.assertRaises(GitHubToolError) as caught:
                run_gh(args)
            self.assertEqual(caught.exception.code, "invalid_arguments")
        run.assert_not_called()

    @patch("subprocess.run")
    def test_cli_uses_literal_arguments_and_bounded_noninteractive_execution(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "result\n", "")
        args = [
            "issue",
            "create",
            "--repo",
            "vaishnavJa/Chatty",
            "--title",
            "$(id); `id`",
        ]
        self.assertEqual(run_gh(args), "result\n")
        positional, options = run.call_args
        self.assertEqual(positional, (["gh", *args],))
        self.assertFalse(options["shell"])
        self.assertEqual(options["timeout"], 30)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertTrue(options["capture_output"])
        self.assertEqual(options["env"]["GH_HOST"], "github.com")
        self.assertEqual(options["env"]["GH_PROMPT_DISABLED"], "1")

    def test_error_has_serializable_contract(self):
        error = GitHubToolError("timeout", "Request timed out.", uncertain=True)
        self.assertEqual(
            error.as_dict(),
            {"code": "timeout", "message": "Request timed out.", "uncertain": True},
        )
        self.assertEqual(str(error), "Request timed out.")


if __name__ == "__main__":
    unittest.main()
