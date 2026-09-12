"""One session registry and one deduplicating executor per local server.

The browser owns function-event dispatch. This module never opens a sideband.
"""

import asyncio
import copy
import importlib
import inspect
import json
import threading
import time
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from chatty.config import Settings
from chatty.integrations.github.dedup import CallLedger

ALLOWED_TOOLS = frozenset(
    {
        "list_recent_commits",
        "list_open_pull_requests",
        "list_open_issues",
        "create_issue",
    }
)


class ExecutorError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class ToolRegistry:
    """Use the durable GitHub adapter; two-argument runners are test fixtures."""

    def __init__(
        self,
        schemas: list[dict],
        execute_tool=None,
        *,
        execute_call=None,
        available=True,
    ):
        self.schemas = copy.deepcopy(schemas)
        self.execute_tool = execute_tool
        self.execute_call = execute_call
        self.available = available
        self.validators = {}
        for schema in self.schemas:
            name = schema.get("name")
            if (
                schema.get("type") != "function"
                or name not in ALLOWED_TOOLS
                or name in self.validators
                or schema.get("parameters", {}).get("type") != "object"
            ):
                raise ValueError("Invalid GitHub tool schema")
            Draft202012Validator.check_schema(schema["parameters"])
            self.validators[name] = Draft202012Validator(schema["parameters"])
        if self.schemas and not (callable(execute_call) or callable(execute_tool)):
            raise ValueError("A tool runner must be callable")

    @classmethod
    def from_module(cls) -> "ToolRegistry":
        try:
            module = importlib.import_module("chatty.agents.tools")
        except ModuleNotFoundError as error:
            if error.name != "chatty.agents.tools":
                raise  # A broken real module must never look like a missing feature.
            return cls([], available=False)
        # The production module must expose its durable, authorized adapter.
        # Falling back to execute_tool here would silently bypass the ledger.
        return cls(module.TOOL_SCHEMAS, execute_call=module.execute_call)

    def validate(self, name: str, arguments: dict) -> None:
        if not self.available:
            raise ExecutorError(
                503, "tools_unavailable", "The GitHub tool module is not installed yet."
            )
        if name not in self.validators:
            raise ExecutorError(400, "unknown_tool", "Unknown or unavailable tool.")
        try:
            self.validators[name].validate(arguments)
        except ValidationError:
            raise ExecutorError(
                400, "invalid_arguments", "Arguments do not match the tool schema."
            ) from None

    def run(
        self,
        session_id: str,
        call_id: str,
        name: str,
        arguments: dict,
        *,
        approved,
        ledger,
    ) -> Any:
        if self.execute_call is not None:
            if name == "create_issue":
                Path(ledger.path).parent.mkdir(parents=True, exist_ok=True)
            result = self.execute_call(
                session_id,
                call_id,
                name,
                arguments,
                explicit_user_request=approved,
                ledger=ledger,
            )
            if (
                not isinstance(result, dict)
                or result.get("call_id") != call_id
                or not isinstance(result.get("output"), str)
            ):
                raise ValueError("Invalid GitHub call receipt")
            return json.loads(result["output"])
        result = self.execute_tool(name, arguments)
        if inspect.isawaitable(result):
            # Each HTTP handler has its own thread; support sync and async exports.
            async def await_result():
                return await result

            return asyncio.run(await_result())
        return result


@dataclass
class Call:
    fingerprint: str
    started: bool = False
    result: Future = field(default_factory=Future)


@dataclass
class Session:
    created: float
    tools: ToolRegistry
    calls: dict[str, Call] = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, settings: Settings, *, clock=time.monotonic):
        self.settings = settings
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()
        self.ledger = CallLedger(settings.ledger_path)

    def _prune(self) -> None:
        now = self.clock()
        for key, session in list(self.sessions.items()):
            if now - session.created >= self.settings.session_ttl_seconds and all(
                not call.started or call.result.done()
                for call in session.calls.values()
            ):
                del self.sessions[key]

    def ensure_capacity(self) -> None:
        with self.lock:
            self._prune()
            if len(self.sessions) >= self.settings.max_sessions:
                raise ExecutorError(
                    503,
                    "session_limit",
                    "Local session limit reached; restart after ending old sessions.",
                )

    def register(self, session_id: str, tools: ToolRegistry) -> None:
        with self.lock:
            # Never overwrite completed receipts if an upstream ID is repeated.
            if session_id not in self.sessions:
                self.sessions[session_id] = Session(self.clock(), tools)

    def execute(
        self,
        session_id: str,
        call_id: str,
        name: str,
        arguments: dict,
        *,
        approved=False,
    ) -> dict:
        if type(approved) is not bool:
            raise ExecutorError(400, "invalid_approval", "Approval must be a boolean.")
        # Compute before tool execution so any mutation by a tool cannot change
        # the identity of a delivered call.
        fingerprint = json.dumps([name, arguments], sort_keys=True, allow_nan=False)
        with self.lock:
            self._prune()
            session = self.sessions.get(session_id)
            if (
                session is None
                or self.clock() - session.created >= self.settings.session_ttl_seconds
            ):
                raise ExecutorError(
                    404,
                    "unknown_session",
                    "Unknown or expired Live session. Start a new session.",
                )
            session.tools.validate(name, arguments)
            call = session.calls.get(call_id)
            if call is not None and call.fingerprint != fingerprint:
                raise ExecutorError(
                    409,
                    "call_conflict",
                    "This call ID already belongs to different arguments or a different tool.",
                )
            if call is None:
                if len(session.calls) >= self.settings.max_calls_per_session:
                    raise ExecutorError(
                        429,
                        "call_limit",
                        "Session tool-call limit reached. Start a new session.",
                    )
                call = Call(fingerprint)
                session.calls[call_id] = call  # Reserve BEFORE any side effect.
            if name == "create_issue" and not approved and not call.started:
                # Bind the exact proposed payload but do not cache a final denial:
                # the human may approve this same call after reviewing it in UI.
                return {
                    "call_id": call_id,
                    "output": json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "code": "authorization_required",
                                "message": "Review the exact issue title and body, then click Create issue.",
                                "uncertain": False,
                            },
                        }
                    ),
                }
            owner = not call.started
            call.started = True
        if owner:
            try:
                result = session.tools.run(
                    session_id,
                    call_id,
                    name,
                    copy.deepcopy(arguments),
                    approved=approved,
                    ledger=self.ledger,
                )
                # Permit a structured object or an already-serialized JSON result.
                if isinstance(result, str):
                    result = json.loads(result)
                output = json.dumps(result, ensure_ascii=False, allow_nan=False)
                output = self.settings.redact(output)
            except Exception:
                # A timeout/exception may follow a successful remote write. Cache
                # this outcome permanently for this call; never retry it blindly.
                output = json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "tool_execution_failed",
                            "message": "The tool did not return a confirmed result. Check GitHub before requesting the action again.",
                            "retryable": False,
                        },
                    }
                )
            call.result.set_result({"call_id": call_id, "output": output})
        try:
            return call.result.result(timeout=self.settings.duplicate_wait_seconds)
        except TimeoutError:
            raise ExecutorError(
                504,
                "tool_still_running",
                "This call is still running. Retry only with the same session ID, call ID, and arguments.",
            ) from None
