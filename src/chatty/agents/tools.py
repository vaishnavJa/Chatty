"""Allowlisted GitHub tools for the backend's Live function-call adapter.

Backend writes MUST use execute_call with a durable ledger, deriving
explicit_user_request from trusted user intent, never model arguments or repo text.
execute_tool is the trusted low-level dispatcher and does not deduplicate writes.
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
from copy import deepcopy

from chatty.integrations.github import project_tools, repository_tools
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


_LEGACY_SCHEMAS = [
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

_SCREEN_SCHEMA = _schema(
    "read_meeting_screen",
    "Answer a question about one current shared-screen snapshot, if screen sharing "
    "has been enabled. This does not watch a continuous video stream.",
    {
        "question": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "pattern": r"\S",
        }
    },
    ["question"],
)
_CONTEXT_SCHEMA = _schema(
    "read_meeting_context",
    "Read recent raw participant transcript evidence from this Live session, "
    "with fragment references and session audio timestamps. Use when explicitly "
    "asked about the meeting discussion or its proposed decisions. Fragments "
    "may overlap; no speaker identity, final agreement or approval is inferred.",
    {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}},
    [],
)
_MODULES = (repository_tools, project_tools)
TOOL_SCHEMAS = [
    *_LEGACY_SCHEMAS,
    *(schema for module in _MODULES for schema in module.TOOL_SCHEMAS),
    _SCREEN_SCHEMA,
    _CONTEXT_SCHEMA,
]
TOOLS = {schema["name"]: schema for schema in TOOL_SCHEMAS}
if len(TOOLS) != len(TOOL_SCHEMAS):
    raise ValueError("Tool names must be unique across registered adapters")
READ_TOOL_NAMES = (
    frozenset(_READ_NAMES)
    | {"read_meeting_screen", "read_meeting_context"}
    | frozenset(name for module in _MODULES for name in module.READ_TOOLS)
)
WRITE_TOOL_NAMES = frozenset({"create_issue"}) | frozenset(
    name for module in _MODULES for name in module.WRITE_TOOLS
)
TOOL_CAPABILITIES = {
    schema["name"]: {
        "label": schema["name"].replace("_", " ").capitalize(),
        "requires_approval": schema["name"] == "create_issue",
        "destructive": False,
    }
    for schema in (*_LEGACY_SCHEMAS, _SCREEN_SCHEMA, _CONTEXT_SCHEMA)
}
for _module in _MODULES:
    TOOL_CAPABILITIES.update(_module.TOOL_CAPABILITIES)
_TOOL_MODULES = {
    name: module
    for module in _MODULES
    for name in (*module.READ_TOOLS, *module.WRITE_TOOLS)
}
if (
    READ_TOOL_NAMES & WRITE_TOOL_NAMES
    or READ_TOOL_NAMES | WRITE_TOOL_NAMES != TOOLS.keys()
):
    raise ValueError("Every tool must have exactly one read/write classification")


def _failure(code, message, *, uncertain=False):
    return {
        "ok": False,
        "error": {"code": code, "message": message, "uncertain": uncertain},
    }


def _validate(name, arguments, explicit_user_request):
    if type(name) is not str or name not in TOOLS:
        return _failure("unknown_tool", "This tool is not available.")
    if type(arguments) is not dict:
        return _failure("invalid_arguments", "Arguments must be a JSON object.")
    if name in _READ_NAMES:
        return _validate_read(arguments)
    if name == "read_meeting_context":
        return _validate_read(arguments)
    if name == "create_issue":
        return _validate_create(arguments, explicit_user_request)
    if name == "read_meeting_screen":
        question = arguments.get("question")
        if (
            set(arguments) != {"question"}
            or type(question) is not str
            or not 1 <= len(question) <= 2000
            or not question.strip()
            or "\x00" in question
        ):
            return _failure(
                "invalid_arguments", "A nonempty screen question is required."
            )
        return None
    failure = _TOOL_MODULES[name].validate(name, arguments)
    if failure is not None:
        return failure
    if name in WRITE_TOOL_NAMES and explicit_user_request is not True:
        return _failure(
            "authorization_required", "This change requires an explicit user request."
        )
    return None


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
    """Execute one validated operation; app writes must use execute_call."""
    failure = _validate(name, arguments, explicit_user_request)
    if failure is not None:
        return failure
    return _execute_validated(name, arguments)


def _execute_validated(name, arguments):
    """Run an allowlisted operation after validation and write reservation."""
    if name == "read_meeting_context":
        return _failure(
            "meeting_context_required",
            "Meeting context must be read through the registered local Live session.",
        )
    if name == "read_meeting_screen":
        return _failure(
            "screen_context_required",
            "A shared-screen snapshot is required. Enable screen context in the "
            "browser and use the meeting vision endpoint.",
        )
    try:
        if name == "create_issue":
            from chatty.integrations.github.writes import create_issue

            data = create_issue(arguments["title"], arguments["body"])
        elif name in _READ_NAMES:
            from chatty.integrations.github import reads

            data = getattr(reads, name)(limit=arguments.get("limit", 10))
        else:
            data = _TOOL_MODULES[name].execute(name, arguments)
        return {"ok": True, "repository": REPOSITORY, "data": data}
    except GitHubToolError as error:
        return {"ok": False, "error": error.as_dict()}
    except Exception:
        # Do not expose exception text: CLI/library failures can contain credentials.
        return _failure(
            "internal_error",
            "The GitHub operation could not be completed.",
            uncertain=name in WRITE_TOOL_NAMES,
        )


def _write_call(session_id, call_id, name, arguments, ledger):
    path = os.environ.get("CHATTY_GITHUB_LEDGER_PATH")
    if ledger is None and (not path or not path.strip() or path == ":memory:"):
        return _failure(
            "ledger_not_configured",
            "A durable GitHub call ledger must be configured before making changes.",
        )
    try:
        if ledger is None:
            from chatty.integrations.github.dedup import CallLedger

            ledger = CallLedger(path)
        return ledger.run(
            session_id,
            call_id,
            {"name": name, "arguments": arguments},
            lambda: _execute_validated(name, arguments),
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
        type(value) is not str or not value.strip() or len(value) > 256
        for value in (session_id, call_id)
    ):
        result = _failure(
            "invalid_arguments", "session_id and call_id must be non-empty strings."
        )
    else:
        result = _validate(name, arguments, explicit_user_request)
        if result is None:
            # Snapshot validated input so ledger payload and execution agree.
            arguments = deepcopy(arguments)
            if name in WRITE_TOOL_NAMES:
                result = _write_call(session_id, call_id, name, arguments, ledger)
            else:
                result = execute_tool(name, arguments)
    return {"call_id": call_id, "output": json.dumps(result, ensure_ascii=True)}
