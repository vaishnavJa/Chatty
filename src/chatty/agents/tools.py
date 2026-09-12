"""Allowlisted GitHub tools for the backend's Live function-call adapter.

Backend writes MUST use execute_call with a durable ledger, deriving
explicit_user_request from trusted user intent, never model arguments or repo text.
execute_tool is the low-level dispatcher and does not deduplicate writes.
Configure CHATTY_GITHUB_LEDGER_PATH on persistent storage or supply a CallLedger.
Keep session_id and call_id stable across redelivery; never retry uncertain writes.
The backend owns the session registry: authenticate the caller, verify session
ownership, and bind call IDs to that session before invoking this adapter.
The backend also owns packaging/installing the chatty namespace (issue #7).

Example successful read output (an empty repository result is valid)::

    {"ok": true, "repository": "vaishnavJa/Chatty", "data": []}

Example denied write output::

    {"ok": false, "error": {"code": "authorization_required",
     "message": "Creating an issue requires an explicit user request.",
     "uncertain": false}}

execute_call returns {"call_id": "call-123", "output": "<JSON envelope above>"}.
"""

import json
import os

from chatty.integrations.github.transport import REPOSITORY, GitHubToolError

_READ_NAMES = (
    "list_recent_commits",
    "list_open_pull_requests",
    "list_open_issues",
)


def _schema(name, description, properties, required):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS = [
    _schema(
        name,
        f"Read {label} from vaishnavJa/Chatty with source URLs, authors and timestamps.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}},
        [],
    )
    for name, label in zip(
        _READ_NAMES,
        ("recent commits", "open pull requests", "open issues"),
        strict=True,
    )
] + [
    _schema(
        "create_issue",
        "Create one issue in vaishnavJa/Chatty only on an explicit user request.",
        {
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "pattern": r"\S",
            },
            "body": {"type": "string", "maxLength": 65536},
        },
        ["title", "body"],
    )
]


def _failure(code, message, *, uncertain=False):
    return {
        "ok": False,
        "error": {"code": code, "message": message, "uncertain": uncertain},
    }


def _validate(name, arguments, explicit_user_request):
    if type(name) is not str or name not in (*_READ_NAMES, "create_issue"):
        return _failure("unknown_tool", "This tool is not available.")
    if type(arguments) is not dict:
        return _failure("invalid_arguments", "Arguments must be a JSON object.")
    if name in _READ_NAMES:
        return _validate_read(arguments)
    return _validate_create(arguments, explicit_user_request)


def _validate_read(arguments):
    limit = arguments.get("limit", 10)
    if set(arguments) - {"limit"} or type(limit) is not int or not 1 <= limit <= 100:
        return _failure(
            "invalid_arguments", "Only an integer limit from 1 to 100 is allowed."
        )
    return None


def _validate_create(arguments, explicit_user_request):
    if set(arguments) != {"title", "body"}:
        return _failure("invalid_arguments", "Exactly title and body are required.")
    title, body = arguments["title"], arguments["body"]
    if type(title) is not str or not 1 <= len(title) <= 256 or not title.strip():
        return _failure(
            "invalid_arguments",
            "Title must contain 1 to 256 characters and non-whitespace text.",
        )
    if type(body) is not str or len(body) > 65536:
        return _failure(
            "invalid_arguments", "Body must be a string of at most 65536 characters."
        )
    if explicit_user_request is not True:
        return _failure(
            "authorization_required",
            "Creating an issue requires an explicit user request.",
        )
    return None


def execute_tool(name, arguments, *, explicit_user_request=False):
    """Execute one validated operation; backend writes must use execute_call."""
    failure = _validate(name, arguments, explicit_user_request)
    if failure is not None:
        return failure
    try:
        if name == "create_issue":
            from chatty.integrations.github.writes import create_issue

            data = create_issue(arguments["title"], arguments["body"])
        else:
            from chatty.integrations.github import reads

            data = getattr(reads, name)(limit=arguments.get("limit", 10))
        return {"ok": True, "repository": REPOSITORY, "data": data}
    except GitHubToolError as error:
        return {"ok": False, "error": error.as_dict()}
    except Exception:
        # Do not expose exception text: CLI/library failures can contain credentials.
        return _failure(
            "internal_error",
            "The GitHub operation could not be completed.",
            uncertain=name == "create_issue",
        )


def _create_call(session_id, call_id, name, arguments, ledger):
    path = os.environ.get("CHATTY_GITHUB_LEDGER_PATH")
    if ledger is None and (not path or not path.strip() or path == ":memory:"):
        return _failure(
            "ledger_not_configured",
            "A durable GitHub call ledger must be configured before creating issues.",
        )
    try:
        if ledger is None:
            from chatty.integrations.github.dedup import CallLedger

            ledger = CallLedger(path)
        return ledger.run(
            session_id,
            call_id,
            {"name": name, "arguments": arguments},
            lambda: execute_tool(name, arguments, explicit_user_request=True),
        )
    except GitHubToolError as error:
        return {"ok": False, "error": error.as_dict()}
    except Exception:
        return _failure(
            "ledger_error",
            "The call ledger could not confirm this operation. Do not retry with a new call ID.",
            uncertain=True,
        )


def execute_call(
    session_id, call_id, name, arguments, *, explicit_user_request=False, ledger=None
):
    """Return a Live call response; validate before reserving any write."""
    if any(
        type(value) is not str or not value.strip() for value in (session_id, call_id)
    ):
        result = _failure(
            "invalid_arguments", "session_id and call_id must be non-empty strings."
        )
    else:
        result = _validate(name, arguments, explicit_user_request)
        if result is None:
            # Snapshot validated input so ledger payload and execution agree.
            arguments = arguments.copy()
            if name == "create_issue":
                result = _create_call(session_id, call_id, name, arguments, ledger)
            else:
                result = execute_tool(name, arguments)
    return {"call_id": call_id, "output": json.dumps(result, ensure_ascii=True)}
