"""Bounded, fixture-testable GitHub reads for the supported repository."""

import re
from datetime import datetime

from . import transport
from .transport import REPOSITORY, GitHubToolError


def _invalid_response():
    return GitHubToolError(
        "invalid_response", "GitHub returned an invalid read response."
    )


def _limit(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise GitHubToolError(
            "invalid_arguments", "limit must be an integer from 1 to 100."
        )
    return value


def _object(value):
    if not isinstance(value, dict):
        raise _invalid_response()
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response()
    return value


def _timestamp(value):
    value = _text(value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid_response() from None
    if parsed.tzinfo is None:
        raise _invalid_response()
    return value


def _url(value, suffix):
    if value != f"https://github.com/{REPOSITORY}/{suffix}":
        raise _invalid_response()
    return value


def _author(row):
    if "author" not in row:
        raise _invalid_response()
    value = row["author"]
    if value is None:
        return None
    return _text(_object(value).get("login"))


def _normalize_commit(value):
    row = _object(value)
    sha = _text(row.get("sha"))
    if re.fullmatch(r"[0-9a-fA-F]{40}", sha) is None:
        raise _invalid_response()
    commit = _object(row.get("commit"))
    identity = _object(commit.get("author"))
    author = _author(row)
    if author is None:
        author = _text(identity.get("name"))
    return {
        "sha": sha,
        "url": _url(row.get("html_url"), f"commit/{sha}"),
        "author": author,
        "created_at": _timestamp(identity.get("date")),
        "message": _text(commit.get("message")),
    }


def _normalize_item(value, kind):
    row = _object(value)
    number = row.get("number")
    if type(number) is not int or number < 1:
        raise _invalid_response()
    return {
        "number": number,
        "title": _text(row.get("title")),
        "url": _url(row.get("url"), f"{kind}/{number}"),
        "author": _author(row),
        "created_at": _timestamp(row.get("createdAt")),
    }


def _rows(args, limit):
    rows = transport.run_json(args)
    if not isinstance(rows, list) or len(rows) > limit:
        raise _invalid_response()
    return rows


def list_recent_commits(limit: int = 10) -> list[dict]:
    """Return commits, using Git author name when no account is linked."""
    limit = _limit(limit)
    rows = _rows(
        ["api", "--method", "GET", f"repos/{REPOSITORY}/commits?per_page={limit}"],
        limit,
    )
    return [_normalize_commit(row) for row in rows]


def _list_open(command, kind, limit):
    limit = _limit(limit)
    rows = _rows(
        [
            command,
            "list",
            "--repo",
            REPOSITORY,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,author,createdAt",
        ],
        limit,
    )
    return [_normalize_item(row, kind) for row in rows]


def list_open_pull_requests(limit: int = 10) -> list[dict]:
    """Return open pull requests, preserving empty results."""
    return _list_open("pr", "pull", limit)


def list_open_issues(limit: int = 10) -> list[dict]:
    """Use issue list so pull requests are never mixed into issue results."""
    return _list_open("issue", "issues", limit)
