"""Repository-fixed GitHub operations; app authorization belongs in execute_call.

All writes must pass the app's concrete approval and durable call ledger. This
module performs only validation and the low-level operation; it never grants
permission, retries writes, changes credentials, or runs arbitrary commands.
"""

import base64
import binascii
import json
import os
import re
import subprocess
import tempfile
from urllib.parse import quote, urlencode

from jsonschema import Draft202012Validator

from .transport import GH_TIMEOUT_SECONDS, REPOSITORY, GitHubToolError

_REPO_URL = f"https://github.com/{REPOSITORY}"
_API_ROOT = f"repos/{REPOSITORY}"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_TEXT_BYTES = 64 * 1024
_MAX_PAGE_TEXT = 128 * 1024
_SHA_PATTERN = r"^[0-9a-fA-F]{40}$"
_ID = {"type": "integer", "minimum": 1, "maximum": 9007199254740991}
_SHA = {"type": "string", "pattern": _SHA_PATTERN}
_REF = {"type": "string", "minLength": 1, "maxLength": 200}
_PATH = {"type": "string", "minLength": 1, "maxLength": 1024}
_TITLE = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"}
_BODY = {"type": "string", "maxLength": 65536}
_MESSAGE = {"type": "string", "minLength": 1, "maxLength": 4096, "pattern": r"\S"}
_PAGE = {
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    "page": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1},
}


def _schema(name, description, properties, required=()):
    return {
        "type": "function",
        "name": name,
        "description": description + " Repository is fixed to vaishnavJa/Chatty.",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS = [
    _schema("get_repository", "Read repository metadata and default branch.", {}),
    _schema(
        "get_issue",
        "Read an issue, body, assignees, labels and state.",
        {"issue_number": _ID},
        ["issue_number"],
    ),
    _schema(
        "list_issue_comments",
        "Read a bounded page of issue or PR discussion comments.",
        {"issue_number": _ID, **_PAGE},
        ["issue_number"],
    ),
    _schema(
        "update_issue",
        "Edit an issue or its labels, assignees, milestone, or open/closed state. Supplied labels and assignees replace those lists; empty lists clear them. Requires approval.",
        {
            "issue_number": _ID,
            "title": _TITLE,
            "body": _BODY,
            "state": {"type": "string", "enum": ["open", "closed"]},
            "labels": {
                "type": "array",
                "maxItems": 50,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "assignees": {
                "type": "array",
                "maxItems": 10,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$",
                },
            },
            "milestone": {"anyOf": [_ID, {"type": "null"}]},
        },
        ["issue_number"],
    ),
    _schema(
        "add_issue_comment",
        "Add an issue or PR discussion comment. Requires approval.",
        {"issue_number": _ID, "body": {**_BODY, "minLength": 1, "pattern": r"\S"}},
        ["issue_number", "body"],
    ),
    _schema(
        "update_issue_comment",
        "Edit an existing discussion comment by its numeric comment ID. Requires approval.",
        {"comment_id": _ID, "body": {**_BODY, "minLength": 1, "pattern": r"\S"}},
        ["comment_id", "body"],
    ),
    _schema(
        "get_pull_request",
        "Read a PR, its head SHA, branch names and merge state.",
        {"pull_number": _ID},
        ["pull_number"],
    ),
    _schema(
        "list_pull_request_files",
        "Read one bounded page of a PR's changed filenames, statistics, and text patches. Sensitive file patches are omitted.",
        {"pull_number": _ID, **_PAGE},
        ["pull_number"],
    ),
    _schema(
        "create_pull_request",
        "Open a PR between branches in this repository. Requires approval.",
        {
            "title": _TITLE,
            "body": _BODY,
            "head": _REF,
            "base": _REF,
            "draft": {"type": "boolean", "default": True},
        },
        ["title", "body", "head", "base"],
    ),
    _schema(
        "update_pull_request",
        "Edit a PR title/body, base branch or open/closed state. Requires approval.",
        {
            "pull_number": _ID,
            "title": _TITLE,
            "body": _BODY,
            "base": _REF,
            "state": {"type": "string", "enum": ["open", "closed"]},
        },
        ["pull_number"],
    ),
    _schema(
        "merge_pull_request",
        "Merge a PR only if its current head matches expected_head_sha. GitHub branch protections apply. Requires approval.",
        {
            "pull_number": _ID,
            "expected_head_sha": _SHA,
            "merge_method": {
                "type": "string",
                "enum": ["merge", "squash", "rebase"],
                "default": "squash",
            },
        },
        ["pull_number", "expected_head_sha"],
    ),
    _schema(
        "list_branches",
        "List one bounded page of branches and current commit SHAs.",
        _PAGE,
    ),
    _schema(
        "create_branch",
        "Create a new branch at an existing repository commit SHA. Does not overwrite branches. Requires approval.",
        {"branch": _REF, "sha": _SHA},
        ["branch", "sha"],
    ),
    _schema(
        "delete_branch",
        "Delete a non-default branch; protected branches are rejected. Requires approval.",
        {"branch": _REF},
        ["branch"],
    ),
    _schema(
        "list_repository_files",
        "List a directory's entries at a branch or commit. Empty path lists the root; content is not returned.",
        {"path": {**_PATH, "minLength": 0, "default": ""}, "ref": _REF, **_PAGE},
    ),
    _schema(
        "read_repository_file",
        "Read up to 64 KiB of UTF-8 file text plus its blob SHA. Binary, oversized, symlink, and sensitive content is omitted or rejected.",
        {"path": _PATH, "ref": _REF},
        ["path"],
    ),
    _schema(
        "update_repository_file",
        "Create or replace a UTF-8 file on an explicit existing branch. expected_sha is required to replace a file; omit only when creating a new path. Requires approval.",
        {
            "path": _PATH,
            "branch": _REF,
            "content": _BODY,
            "message": _MESSAGE,
            "expected_sha": _SHA,
        },
        ["path", "branch", "content", "message"],
    ),
    _schema(
        "delete_repository_file",
        "Delete a file on an explicit branch only when its blob matches expected_sha. Requires approval.",
        {"path": _PATH, "branch": _REF, "message": _MESSAGE, "expected_sha": _SHA},
        ["path", "branch", "message", "expected_sha"],
    ),
    _schema(
        "list_workflow_runs",
        "Read one bounded page of workflow run status and URLs. Does not read logs or secrets.",
        _PAGE,
    ),
    _schema(
        "rerun_workflow",
        "Request a rerun of an existing workflow run using the original run's privileges and code. May deploy or incur cost; requires approval.",
        {"run_id": _ID},
        ["run_id"],
    ),
]

WRITE_TOOLS = frozenset(
    {
        "update_issue",
        "add_issue_comment",
        "update_issue_comment",
        "create_pull_request",
        "update_pull_request",
        "merge_pull_request",
        "create_branch",
        "delete_branch",
        "update_repository_file",
        "delete_repository_file",
        "rerun_workflow",
    }
)
READ_TOOLS = frozenset(schema["name"] for schema in TOOL_SCHEMAS) - WRITE_TOOLS
TOOL_CAPABILITIES = {
    schema["name"]: {
        "label": schema["name"].replace("_", " ").capitalize(),
        "requires_approval": schema["name"] in WRITE_TOOLS,
        "destructive": schema["name"]
        in {
            "delete_branch",
            "delete_repository_file",
            "merge_pull_request",
            "rerun_workflow",
        },
    }
    for schema in TOOL_SCHEMAS
}
_VALIDATORS = {
    schema["name"]: Draft202012Validator(schema["parameters"])
    for schema in TOOL_SCHEMAS
}


def _error(code, message, *, uncertain=False):
    return GitHubToolError(code, message, uncertain=uncertain)


def _invalid(message="GitHub returned an invalid response.", *, uncertain=False):
    return _error("invalid_response", message, uncertain=uncertain)


def _check_text(value):
    if type(value) is float:
        raise _error(
            "invalid_arguments", "Numeric IDs and pagination must be integers."
        )
    if isinstance(value, dict):
        for item in value.values():
            _check_text(item)
    elif isinstance(value, list):
        for item in value:
            _check_text(item)
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise _error(
                "invalid_arguments", "Arguments must be valid Unicode."
            ) from None
        if "\x00" in value:
            raise _error("invalid_arguments", "Arguments cannot contain null bytes.")


def _check_ref(value):
    if (
        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}", value)
        or value == "HEAD"
        or ".." in value
        or "//" in value
        or value.endswith(("/", "."))
        or any(
            part.startswith(".") or part.endswith(".lock") for part in value.split("/")
        )
    ):
        raise _error(
            "invalid_arguments",
            "Use an exact branch name or commit SHA without ref syntax or traversal.",
        )


def _sensitive_path(path):
    parts = path.lower().split("/")
    source_file = parts[-1].endswith(
        (
            ".py",
            ".pyi",
            ".js",
            ".mjs",
            ".cjs",
            ".jsx",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".cs",
            ".sh",
        )
    )
    for part in parts:
        if part in {
            ".git",
            ".ssh",
            ".aws",
            ".azure",
            ".gnupg",
            ".credentials",
            ".secrets",
        }:
            return True
        if re.search(r"(?:^|\.)env(?:\.|$)", part) and part not in {
            ".env.example",
            ".env.sample",
            ".env.template",
        }:
            return True
        if (
            part.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
            or re.fullmatch(r"id_(rsa|dsa|ecdsa|ed25519)(\.pub)?", part)
            or re.search(r"(?:^|[_.-])private[-_]?key(?:[_.-]|$)", part)
        ):
            return True
        # Credential-management modules are ordinary repository source. Keep
        # blocking credential data and hidden credential stores, not module names.
        if not source_file and re.search(
            r"(?:^|[_.-])(credentials?|secrets?|service[-_]?account)(?:[_.-]|$)", part
        ):
            return True
    return False


def _check_path(value, *, root=False):
    if root and value == "":
        return
    if (
        not value
        or value.startswith("/")
        or len(value) > 1024
        or any(c in value for c in "\\?#%")
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise _error(
            "invalid_arguments",
            "Use a relative repository path without traversal or URL syntax.",
        )
    if _sensitive_path(value):
        raise _error(
            "sensitive_path",
            "Credential, private-key and real environment files are excluded from automated repository tools.",
        )


def validate(name, arguments):
    """Return None or the adapter's safe failure envelope; no GitHub calls."""
    if type(name) is not str or name not in _VALIDATORS:
        return {
            "ok": False,
            "error": _error(
                "unknown_tool", "This repository tool is unavailable."
            ).as_dict(),
        }
    try:
        if type(arguments) is not dict or not _VALIDATORS[name].is_valid(arguments):
            raise _error(
                "invalid_arguments",
                "Arguments must match this tool's schema; unknown fields are not allowed.",
            )
        _check_text(arguments)
        for key in ("sha", "expected_sha", "expected_head_sha"):
            if (
                key in arguments
                and re.fullmatch(r"[0-9a-fA-F]{40}", arguments[key]) is None
            ):
                raise _error(
                    "invalid_arguments", "Supply an exact 40-character hexadecimal SHA."
                )
        for login in arguments.get("assignees", []):
            if (
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login)
                is None
            ):
                raise _error(
                    "invalid_arguments", "Supply exact GitHub usernames for assignees."
                )
        for key in ("branch", "ref", "base", "head"):
            if key in arguments:
                _check_ref(arguments[key])
        if "path" in arguments:
            _check_path(arguments["path"], root=name == "list_repository_files")
        if name in {"update_issue", "update_pull_request"} and len(arguments) < 2:
            raise _error("invalid_arguments", "Supply at least one field to update.")
        if name == "create_pull_request" and arguments["head"] == arguments["base"]:
            raise _error("invalid_arguments", "Pull request head and base must differ.")
        if (
            "content" in arguments
            and len(arguments["content"].encode("utf-8")) > _MAX_TEXT_BYTES
        ):
            raise _error(
                "invalid_arguments", "File content is limited to 64 KiB of UTF-8 text."
            )
    except GitHubToolError as error:
        return {"ok": False, "error": error.as_dict()}
    return None


def _cli_error(returncode, diagnostic, *, write):
    text = diagnostic.lower()
    status_match = re.search(r"http\s+(\d{3})", text)
    status = int(status_match.group(1)) if status_match else None
    # A definitive rejection is safe to correct and resubmit, unlike timeouts/5xx.
    uncertain = write and (status is None or status >= 500)
    if (
        returncode == 4
        or status == 401
        or "bad credentials" in text
        or "gh auth login" in text
    ):
        return _error(
            "auth_required",
            "GitHub authentication is required. Sign in with gh auth login.",
        )
    if (
        status == 403
        or "resource not accessible" in text
        or "permission denied" in text
    ):
        return _error(
            "permission_denied",
            "GitHub denied access. Check the requested repository permission or branch protection.",
        )
    if status == 404:
        return _error(
            "not_found",
            "The requested repository resource was not found or is not accessible.",
        )
    if status in {409, 422}:
        return _error(
            "conflict",
            "GitHub rejected the change. Refresh the resource and check its SHA, fields, or branch protections.",
        )
    if status == 405:
        return _error(
            "merge_blocked",
            "GitHub cannot merge this pull request under the current branch rules or PR state.",
        )
    if status == 429 or "rate limit" in text:
        return _error(
            "rate_limited",
            "GitHub rate-limited this request. Wait before retrying.",
            uncertain=uncertain,
        )
    return _error(
        "github_error",
        "GitHub request failed. Check its outcome before retrying a write.",
        uncertain=uncertain,
    )


def _reject_constant(value):
    raise ValueError("Non-JSON numeric constant")


def _api(method, suffix="", *, payload=None, query=None, empty=False):
    """Internal REST endpoint builder; stdout is spooled and reads are bounded."""
    endpoint = _API_ROOT + (f"/{suffix}" if suffix else "")
    if query:
        endpoint += "?" + urlencode(query)
    args = [
        "gh",
        "api",
        "--hostname",
        "github.com",
        "--method",
        method,
        "--header",
        "Accept: application/vnd.github+json",
        "--header",
        "X-GitHub-Api-Version: 2022-11-28",
        endpoint,
    ]
    if payload is not None:
        args += ["--input", "-"]
    env = os.environ.copy()
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    env.pop("GH_DEBUG", None)
    env.pop("GH_REPO", None)
    attempted = False
    write = method != "GET"
    try:
        with (
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as diagnostics,
        ):
            attempted = True
            result = subprocess.run(
                args,
                input=json.dumps(payload, ensure_ascii=True)
                if payload is not None
                else "",
                stdout=output,
                stderr=diagnostics,
                text=True,
                encoding="utf-8",
                shell=False,
                check=False,
                timeout=GH_TIMEOUT_SECONDS,
                env=env,
            )
            diagnostics.seek(0)
            if result.returncode:
                raise _cli_error(
                    result.returncode,
                    diagnostics.read(65536).decode("utf-8", errors="replace"),
                    write=write,
                )
            output.seek(0)
            raw = output.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise _error(
                    "response_too_large",
                    "GitHub response exceeded the supported size; narrow the request.",
                    uncertain=write,
                )
    except subprocess.TimeoutExpired:
        raise _error(
            "timeout",
            "GitHub request timed out. Check its outcome before retrying.",
            uncertain=write,
        ) from None
    except PermissionError:
        raise _error(
            "permission_denied", "Permission to execute GitHub CLI was denied."
        ) from None
    except FileNotFoundError:
        raise _error(
            "gh_unavailable", "GitHub CLI could not be started. Check its installation."
        ) from None
    except OSError:
        raise _error(
            "local_io_error",
            "Could not execute or collect the GitHub request.",
            uncertain=attempted and write,
        ) from None
    if empty and not raw.strip():
        return None
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _error(
            "invalid_json", "GitHub returned an invalid JSON response.", uncertain=write
        ) from None


def _object(value):
    if not isinstance(value, dict):
        raise _invalid()
    return value


def _rows(value, limit):
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(row, dict) for row in value)
    ):
        raise _invalid()
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch(_SHA_PATTERN, value) is None:
        raise _invalid()
    return value


def _number(value):
    if type(value) is not int or value < 1:
        raise _invalid()
    return value


def _clip(value, limit=_MAX_TEXT_BYTES):
    if value is None:
        return None, False
    if not isinstance(value, str):
        raise _invalid()
    raw = value.encode("utf-8")
    return raw[:limit].decode("utf-8", errors="ignore"), len(raw) > limit


def _url(value, suffix):
    expected = f"{_REPO_URL}/{suffix}"
    if value != expected:
        raise _invalid(
            "GitHub did not confirm a resource URL in the allowed repository."
        )
    return expected


def _identity(value):
    return _object(value).get("login") if value is not None else None


def _issue(row, number=None, *, pull=False):
    row = _object(row)
    returned = _number(row.get("number"))
    if number is not None and number != returned:
        raise _invalid()
    kind = "pull" if pull else "issues"
    body, truncated = _clip(row.get("body"))
    result = {
        "number": returned,
        "url": _url(row.get("html_url"), f"{kind}/{returned}"),
        "title": row.get("title"),
        "body": body,
        "body_truncated": truncated,
        "state": row.get("state"),
        "author": _identity(row.get("user")),
        "assignees": [_identity(item) for item in row.get("assignees", [])],
        "labels": [_object(item).get("name") for item in row.get("labels", [])],
        "milestone": None
        if row.get("milestone") is None
        else {key: row["milestone"].get(key) for key in ("number", "title", "state")},
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if pull:
        head, base = _object(row.get("head")), _object(row.get("base"))
        result.update(
            head=head.get("ref"),
            head_sha=_sha(head.get("sha")),
            base=base.get("ref"),
            draft=row.get("draft"),
            merged=row.get("merged"),
            mergeable=row.get("mergeable"),
            mergeable_state=row.get("mergeable_state"),
        )
    return result


def _comment(row, *, issue_number=None, comment_id=None, limit=_MAX_TEXT_BYTES):
    row = _object(row)
    returned = _number(row.get("id"))
    if comment_id is not None and comment_id != returned:
        raise _invalid()
    url = row.get("html_url")
    match = re.fullmatch(
        rf"{re.escape(_REPO_URL)}/(?:issues|pull)/([1-9][0-9]*)#issuecomment-{returned}",
        url or "",
    )
    if match is None or (
        issue_number is not None and int(match.group(1)) != issue_number
    ):
        raise _invalid()
    body, truncated = _clip(row.get("body"), limit)
    return {
        "comment_id": returned,
        "issue_number": int(match.group(1)),
        "url": url,
        "body": body,
        "body_truncated": truncated,
        "author": _identity(row.get("user")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _pagination(args):
    return {"per_page": args.get("limit", 20), "page": args.get("page", 1)}


def _page(items, args, url):
    return {
        "items": items,
        "page": args.get("page", 1),
        "limit": args.get("limit", 20),
        "has_more": len(items) == args.get("limit", 20),
        "url": url,
    }


def _contents(args):
    query = {"ref": args["ref"]} if args.get("ref") else None
    path = args.get("path", "")
    return _api(
        "GET", "contents" + ("/" + quote(path, safe="/") if path else ""), query=query
    )


def _file_metadata(row, path=None):
    row = _object(row)
    returned = row.get("path")
    if type(returned) is not str or (path is not None and path != returned):
        raise _invalid()
    size = row.get("size")
    if type(size) is not int or size < 0:
        raise _invalid()
    return {
        "path": returned,
        "sha": _sha(row.get("sha")),
        "size": size,
        "type": row.get("type"),
    }


def _get_repository():
    row = _object(_api("GET"))
    if row.get("full_name") != REPOSITORY or row.get("html_url") != _REPO_URL:
        raise _invalid("GitHub did not confirm the allowed repository.")
    default = row.get("default_branch")
    if type(default) is not str or not default:
        raise _invalid()
    return {
        "repository": REPOSITORY,
        "url": _REPO_URL,
        "default_branch": default,
        **{
            key: row.get(key)
            for key in (
                "description",
                "visibility",
                "private",
                "archived",
                "open_issues_count",
                "permissions",
            )
        },
    }


def _tree_entry(path, ref):
    # Contents API follows symlinks to ordinary files. Resolve Git modes first
    # and read the exact blob so an innocuous alias cannot disclose .env.
    tree = _object(
        _api("GET", "git/trees/" + quote(ref, safe=""), query={"recursive": "1"})
    )
    if tree.get("truncated") is not False:
        raise _error(
            "response_too_large",
            "Repository tree was incomplete; this file cannot be safely resolved.",
        )
    rows = _rows(tree.get("tree"), 100000)
    ancestors = {path.rsplit("/", count)[0] for count in range(1, path.count("/") + 1)}
    found = None
    for row in rows:
        if row.get("path") in ancestors and row.get("mode") != "040000":
            raise _error(
                "invalid_arguments",
                "A repository path cannot traverse a symlink or submodule.",
            )
        if row.get("path") == path:
            found = row
    if found is None:
        raise _error(
            "not_found", "The file does not exist at the selected repository revision."
        )
    mode = found.get("mode")
    kind = (
        "file"
        if mode in {"100644", "100755"}
        else "symlink"
        if mode == "120000"
        else "directory"
        if mode == "040000"
        else "submodule"
    )
    return _file_metadata({**found, "type": kind, "size": found.get("size", 0)}, path)


def _read_file(args):
    result = _tree_entry(args["path"], args.get("ref") or "HEAD")
    ref = args.get("ref") or "HEAD"
    result["url"] = (
        f"{_REPO_URL}/blob/{quote(ref, safe='/')}/{quote(args['path'], safe='/')}"
    )
    if result["type"] != "file":
        result.update(content=None, content_omitted="Only regular files are read.")
        return result
    if result["size"] > _MAX_TEXT_BYTES:
        result.update(
            content=None, content_omitted="File exceeds the 64 KiB text limit."
        )
        return result
    row = _object(_api("GET", "git/blobs/" + result["sha"]))
    if _sha(row.get("sha")) != result["sha"] or row.get("size") != result["size"]:
        raise _invalid()
    if row.get("encoding") != "base64" or not isinstance(row.get("content"), str):
        raise _invalid()
    try:
        raw = base64.b64decode("".join(row["content"].split()), validate=True)
    except (ValueError, binascii.Error):
        raise _invalid() from None
    if len(raw) > _MAX_TEXT_BYTES or len(raw) != result["size"]:
        raise _invalid()
    try:
        content = raw.decode("utf-8")
        if "\x00" in content:
            raise UnicodeError()
    except UnicodeError:
        result.update(content=None, content_omitted="Binary or non-UTF-8 content.")
    else:
        result.update(content=content, content_omitted=None)
    return result


def _list_files(args):
    rows = _rows(_contents(args), 1000)
    page, limit = args.get("page", 1), args.get("limit", 20)
    selected = rows[(page - 1) * limit : page * limit]
    items = [
        {**_file_metadata(row), "sensitive": _sensitive_path(row["path"])}
        for row in selected
    ]
    result = _page(
        items,
        args,
        f"{_REPO_URL}/tree/{quote(args.get('ref', 'HEAD'), safe='/')}/{quote(args.get('path', ''), safe='/')}",
    )
    result.update(
        has_more=page * limit < len(rows),
        directory_listing_may_be_truncated=len(rows) == 1000,
    )
    return result


def _file_write(name, args):
    # Resolve the branch first: a 404 for a missing branch must never be treated
    # as evidence that a file can safely be created.
    branch = _object(_api("GET", "branches/" + quote(args["branch"], safe="")))
    if branch.get("name") != args["branch"]:
        raise _invalid()
    exists = True
    try:
        current = _tree_entry(args["path"], args["branch"])
    except GitHubToolError as error:
        if (
            error.code != "not_found"
            or name != "update_repository_file"
            or "expected_sha" in args
        ):
            raise
        exists, current = False, None
    if exists:
        if (
            current.get("type") != "file"
            or current.get("target")
            or current.get("submodule_git_url")
        ):
            raise _error(
                "invalid_arguments",
                "Only regular files can be changed through this tool.",
            )
        current_sha = _sha(current.get("sha"))
        if "expected_sha" not in args:
            raise _error(
                "expected_sha_required",
                "Read the file and supply its current blob SHA before replacing it.",
            )
        if args["expected_sha"].lower() != current_sha.lower():
            raise _error(
                "conflict",
                "The file changed since it was read. Refresh its content and SHA before updating.",
            )
    payload = {"branch": args["branch"], "message": args["message"]}
    if exists:
        payload["sha"] = args["expected_sha"]
    if name == "update_repository_file":
        payload["content"] = base64.b64encode(args["content"].encode("utf-8")).decode(
            "ascii"
        )
    method = "PUT" if name == "update_repository_file" else "DELETE"
    row = _object(
        _api(method, "contents/" + quote(args["path"], safe="/"), payload=payload)
    )
    commit = _object(row.get("commit"))
    sha = _sha(commit.get("sha"))
    result = {
        "path": args["path"],
        "branch": args["branch"],
        "commit_sha": sha,
        "url": _url(commit.get("html_url"), f"commit/{sha}"),
        "deleted": name == "delete_repository_file",
    }
    if not result["deleted"]:
        content = _file_metadata(row.get("content"), args["path"])
        result.update(sha=content["sha"], created=not exists)
    return result


def _execute(name, args):
    if name == "get_repository":
        return _get_repository()
    if name in {"get_issue", "update_issue"}:
        number = args["issue_number"]
        payload = {key: value for key, value in args.items() if key != "issue_number"}
        row = _api(
            "GET" if name == "get_issue" else "PATCH",
            f"issues/{number}",
            payload=None if name == "get_issue" else payload,
        )
        return _issue(row, number)
    if name == "list_issue_comments":
        number, limit = args["issue_number"], args.get("limit", 20)
        rows = _rows(
            _api("GET", f"issues/{number}/comments", query=_pagination(args)), limit
        )
        return _page(
            [
                _comment(
                    row,
                    issue_number=number,
                    limit=min(_MAX_TEXT_BYTES, _MAX_PAGE_TEXT // max(1, len(rows))),
                )
                for row in rows
            ],
            args,
            f"{_REPO_URL}/issues/{number}",
        )
    if name == "add_issue_comment":
        number = args["issue_number"]
        return _comment(
            _api("POST", f"issues/{number}/comments", payload={"body": args["body"]}),
            issue_number=number,
        )
    if name == "update_issue_comment":
        return _comment(
            _api(
                "PATCH",
                f"issues/comments/{args['comment_id']}",
                payload={"body": args["body"]},
            ),
            comment_id=args["comment_id"],
        )
    if name in {"get_pull_request", "update_pull_request", "create_pull_request"}:
        number = args.get("pull_number")
        payload = {key: value for key, value in args.items() if key != "pull_number"}
        if name == "create_pull_request":
            payload.setdefault("draft", True)
        method = {
            "get_pull_request": "GET",
            "update_pull_request": "PATCH",
            "create_pull_request": "POST",
        }[name]
        row = _api(
            method,
            f"pulls/{number}" if number is not None else "pulls",
            payload=None if method == "GET" else payload,
        )
        return _issue(row, number, pull=True)
    if name == "list_pull_request_files":
        number, limit = args["pull_number"], args.get("limit", 20)
        rows = _rows(
            _api("GET", f"pulls/{number}/files", query=_pagination(args)), limit
        )
        items = []
        for row in rows:
            path = row.get("filename")
            if not isinstance(path, str):
                raise _invalid()
            sensitive = _sensitive_path(path) or _sensitive_path(
                row.get("previous_filename") or ""
            )
            patch, truncated = _clip(
                None if sensitive else row.get("patch"),
                min(_MAX_TEXT_BYTES, _MAX_PAGE_TEXT // max(1, len(rows))),
            )
            items.append(
                {
                    key: row.get(key)
                    for key in (
                        "filename",
                        "previous_filename",
                        "status",
                        "additions",
                        "deletions",
                        "changes",
                        "sha",
                    )
                }
                | {
                    "patch": patch,
                    "patch_truncated": truncated,
                    "patch_omitted": "Sensitive file." if sensitive else None,
                }
            )
        return _page(items, args, f"{_REPO_URL}/pull/{number}/files")
    if name == "merge_pull_request":
        number = args["pull_number"]
        row = _object(
            _api(
                "PUT",
                f"pulls/{number}/merge",
                payload={
                    "sha": args["expected_head_sha"],
                    "merge_method": args.get("merge_method", "squash"),
                },
            )
        )
        if row.get("merged") is not True:
            raise _error("merge_blocked", "GitHub did not merge this pull request.")
        return {
            "number": number,
            "merged": True,
            "sha": _sha(row.get("sha")),
            "url": f"{_REPO_URL}/pull/{number}",
        }
    if name == "list_branches":
        rows = _rows(
            _api("GET", "branches", query=_pagination(args)), args.get("limit", 20)
        )
        items = []
        for row in rows:
            branch = row.get("name")
            if not isinstance(branch, str):
                raise _invalid()
            items.append(
                {
                    "name": branch,
                    "sha": _sha(_object(row.get("commit")).get("sha")),
                    "protected": row.get("protected"),
                    "url": f"{_REPO_URL}/tree/{quote(branch, safe='/')}",
                }
            )
        return _page(items, args, f"{_REPO_URL}/branches")
    if name == "create_branch":
        # Validate membership in this repository before creating a reference.
        commit = _object(_api("GET", "git/commits/" + args["sha"]))
        if _sha(commit.get("sha")).lower() != args["sha"].lower():
            raise _invalid()
        row = _object(
            _api(
                "POST",
                "git/refs",
                payload={"ref": "refs/heads/" + args["branch"], "sha": args["sha"]},
            )
        )
        sha = _sha(_object(row.get("object")).get("sha"))
        if (
            row.get("ref") != "refs/heads/" + args["branch"]
            or sha.lower() != args["sha"].lower()
        ):
            raise _invalid()
        return {
            "branch": args["branch"],
            "sha": sha,
            "url": f"{_REPO_URL}/tree/{quote(args['branch'], safe='/')}",
        }
    if name == "delete_branch":
        if _get_repository()["default_branch"] == args["branch"]:
            raise _error(
                "protected_branch", "The repository's default branch cannot be deleted."
            )
        row = _object(_api("GET", "branches/" + quote(args["branch"], safe="")))
        if row.get("name") != args["branch"]:
            raise _invalid()
        if row.get("protected") is not False:
            raise _error(
                "protected_branch", "A protected branch cannot be deleted by this tool."
            )
        _api("DELETE", "git/refs/heads/" + quote(args["branch"], safe=""), empty=True)
        return {
            "branch": args["branch"],
            "deleted": True,
            "url": f"{_REPO_URL}/branches",
        }
    if name == "list_repository_files":
        return _list_files(args)
    if name == "read_repository_file":
        return _read_file(args)
    if name in {"update_repository_file", "delete_repository_file"}:
        return _file_write(name, args)
    if name == "list_workflow_runs":
        row = _object(_api("GET", "actions/runs", query=_pagination(args)))
        rows = _rows(row.get("workflow_runs"), args.get("limit", 20))
        items = []
        for run in rows:
            run_id = _number(run.get("id"))
            items.append(
                {
                    key: run.get(key)
                    for key in (
                        "name",
                        "status",
                        "conclusion",
                        "head_branch",
                        "head_sha",
                        "event",
                        "created_at",
                        "updated_at",
                        "run_attempt",
                    )
                }
                | {
                    "run_id": run_id,
                    "url": _url(run.get("html_url"), f"actions/runs/{run_id}"),
                }
            )
        return _page(items, args, f"{_REPO_URL}/actions")
    if name == "rerun_workflow":
        _api("POST", f"actions/runs/{args['run_id']}/rerun", empty=True)
        return {
            "run_id": args["run_id"],
            "rerun_requested": True,
            "url": f"{_REPO_URL}/actions/runs/{args['run_id']}",
        }
    raise _error("unknown_tool", "This repository tool is unavailable.")


def execute(name, arguments):
    """Execute a validated low-level call; callers must authorize/deduplicate writes."""
    failure = validate(name, arguments)
    if failure is not None:
        detail = failure["error"]
        raise GitHubToolError(
            detail["code"], detail["message"], uncertain=detail["uncertain"]
        )
    try:
        return _execute(name, arguments)
    except GitHubToolError as error:
        # A malformed successful write response cannot be treated as safe to retry.
        if name in WRITE_TOOLS and error.code == "invalid_response":
            raise GitHubToolError(error.code, error.message, uncertain=True) from None
        raise
    except Exception:
        # Malformed responses and unexpected CLI/library exceptions can carry
        # credentials in their text. Expose only a safe public classification.
        raise GitHubToolError(
            "internal_error",
            "The repository operation could not be completed.",
            uncertain=name in WRITE_TOOLS,
        ) from None
