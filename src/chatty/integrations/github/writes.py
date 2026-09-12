"""Low-level issue creation; trusted authorization belongs in the dispatcher."""

import re
import tempfile

from .transport import REPOSITORY, GitHubToolError, run_gh


def _validate_text(title: str, body: str) -> None:
    if type(title) is not str or not 1 <= len(title) <= 256 or not title.strip():
        raise GitHubToolError(
            "invalid_arguments", "Title must contain 1–256 characters and not be blank."
        )
    if type(body) is not str or len(body) > 65536:
        raise GitHubToolError(
            "invalid_arguments", "Body must be a string of at most 65536 characters."
        )
    if "\0" in title:
        raise GitHubToolError(
            "invalid_arguments", "Title cannot contain a null character."
        )
    try:
        title.encode("utf-8")
        body.encode("utf-8")
    except UnicodeError:
        raise GitHubToolError(
            "invalid_arguments", "Title and body must be valid Unicode."
        ) from None


def create_issue(title: str, body: str) -> dict:
    """Create once, preserving text and accepting only a confirmed repository URL."""
    _validate_text(title, body)
    attempted = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline=""
        ) as file:
            file.write(body)
            file.flush()
            attempted = True
            output = run_gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    REPOSITORY,
                    "--title=" + title,
                    "--body-file",
                    file.name,
                ]
            )
    except OSError:
        raise GitHubToolError(
            "local_io_error",
            "Could not prepare or clean up the issue request.",
            uncertain=attempted,
        ) from None
    url = output.strip()
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(REPOSITORY)}/issues/([1-9][0-9]*)", url
    )
    if match is None:
        raise GitHubToolError(
            "invalid_response",
            "Issue creation returned no confirmed issue URL.",
            uncertain=True,
        )
    try:
        number = int(match.group(1))
    except ValueError:
        raise GitHubToolError(
            "invalid_response",
            "Issue creation returned an invalid issue number.",
            uncertain=True,
        ) from None
    return {"number": number, "url": url}
