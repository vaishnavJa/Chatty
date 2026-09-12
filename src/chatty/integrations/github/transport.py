"""Private CLI boundary; callers construct allowlisted, repository-fixed arguments."""

import json
import os
import subprocess

REPOSITORY = "vaishnavJa/Chatty"
GH_TIMEOUT_SECONDS = 30


class GitHubToolError(Exception):
    """A safe public error. Messages must never include raw CLI diagnostics."""

    def __init__(self, code: str, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.uncertain = bool(uncertain)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "uncertain": self.uncertain,
        }


def run_gh(args: list[str]) -> str:
    """Run trusted internal arguments, never a model-provided command."""
    if (
        type(args) is not list
        or not args
        or any(type(arg) is not str or "\x00" in arg for arg in args)
    ):
        raise GitHubToolError("invalid_arguments", "Invalid GitHub CLI arguments.")
    uncertain = args[:2] == ["issue", "create"]
    env = os.environ.copy()
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    env.pop("GH_DEBUG", None)
    env.pop("GH_REPO", None)
    try:
        result = subprocess.run(
            ["gh", *args],
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise GitHubToolError(
            "timeout",
            "GitHub request timed out. Check its outcome before retrying.",
            uncertain=uncertain,
        ) from None
    except PermissionError:
        raise GitHubToolError(
            "permission_denied", "Permission to execute GitHub CLI was denied."
        ) from None
    except OSError:
        raise GitHubToolError(
            "gh_unavailable", "GitHub CLI could not be started. Check its installation."
        ) from None
    if result.returncode:
        raise _cli_error(result.returncode, result.stderr, uncertain=uncertain)
    return result.stdout


def _cli_error(returncode: int, stderr: str, *, uncertain: bool) -> GitHubToolError:
    # Diagnostics are inspected only for classification and never returned or logged.
    diagnostic = stderr.lower()
    if returncode == 4 or any(
        marker in diagnostic
        for marker in (
            "http 401",
            "bad credentials",
            "gh auth login",
            "authentication required",
        )
    ):
        return GitHubToolError(
            "auth_required",
            "GitHub authentication is required. Sign in with gh auth login.",
            uncertain=uncertain,
        )
    if any(
        marker in diagnostic
        for marker in (
            "http 403",
            "forbidden",
            "resource not accessible",
            "permission denied",
        )
    ):
        return GitHubToolError(
            "permission_denied",
            "GitHub denied access. Check repository permissions.",
            uncertain=uncertain,
        )
    return GitHubToolError(
        "github_error",
        "GitHub request failed. Check GitHub availability and repository access.",
        uncertain=uncertain,
    )


def run_json(args: list[str]):
    """Decode a CLI JSON response."""
    output = run_gh(args)
    try:
        return json.loads(output, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise GitHubToolError(
            "invalid_json",
            "GitHub returned an invalid JSON response.",
            uncertain=args[:2] == ["issue", "create"],
        ) from None


def _reject_constant(value: str):
    raise ValueError("Non-JSON numeric constant")
