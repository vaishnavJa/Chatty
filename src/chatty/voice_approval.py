"""Action-bound spoken approval for the trusted, same-origin localhost client.

The browser relays Live transcript envelopes and measured playback/input activity.
These are not independently authenticated server events or speaker identification.
Speech segmentation is heuristic; anyone audible in the meeting can answer. This
module prevents stale/model-output evidence and changed proposals in the normal
client flow, but cannot detect fabricated browser evidence or acoustic replay.
Only bounded evidence for the current confirmation is retained, never a meeting.
"""

import copy
import hashlib
import json
import math
import secrets
import threading
import time
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field

from chatty.agents.tools import WRITE_TOOL_NAMES
from chatty.approval_language import (
    ApprovalLanguage,
    confirmation_prompt,
    prompt_input_boundary,
)
from chatty.integrations.gpt_live.executor import ExecutorError

MAX_EVENTS = 128
MAX_TEXT = 16_384
MAX_ATTEMPTS = 32
MAX_CLASSIFIERS = 4


@dataclass
class Approval:
    session_id: str
    call_id: str
    name: str
    arguments: dict
    fingerprint: str
    approval_id: str
    prompt: str
    expires_at: int
    deadline: float
    boundary: float = 0
    state: str = "pending"
    result: Future = field(default_factory=Future)
    attempts: dict = field(default_factory=dict)
    generation: int = 0
    latest_reply: Future | None = None
    attempts_started: int = 0
    checks_in_flight: int = 0
    prompt_seen: bool = False


class VoiceApprovals:
    def __init__(
        self,
        executor,
        *,
        clock=time.monotonic,
        wall_clock=time.time,
        ttl=90,
        language=None,
    ):
        self.executor = executor
        self.clock = clock
        self.wall_clock = wall_clock
        self.ttl = ttl
        self.language = (
            language if language is not None else ApprovalLanguage(executor.settings)
        )
        self.lock = threading.RLock()
        self.approvals = {}
        self.active = {}
        self.seen = {}
        self.timeline = {}

    def _session(self, session_id):
        with self.executor.lock:
            self.executor._prune()
            session = self.executor.sessions.get(session_id)
            if (
                session is None
                or self.executor.clock() - session.created
                >= self.executor.settings.session_ttl_seconds
            ):
                raise ExecutorError(
                    404,
                    "unknown_session",
                    "Unknown or expired Live session. Start a new session.",
                )
            return session

    def _prune(self):
        valid = self.executor.sessions
        for approval_id, approval in list(self.approvals.items()):
            if approval.session_id not in valid and approval.state != "executing":
                del self.approvals[approval_id]
        for mapping in (self.active, self.seen, self.timeline):
            for session_id in list(mapping):
                if session_id not in valid:
                    del mapping[session_id]

    def _lookup(self, session_id, approval_id):
        self._session(session_id)
        approval = self.approvals.get(approval_id)
        if approval is None or approval.session_id != session_id:
            raise ExecutorError(
                404,
                "unknown_approval",
                "This spoken confirmation is not part of this session.",
            )
        if (
            approval.state in {"pending", "armed", "checking_prompt", "classifying"}
            and self.clock() >= approval.deadline
        ):
            self._reject(
                approval,
                "expired",
                "Spoken approval expired. Ask Chatty for a new proposal.",
            )
        return approval

    def _prepared(self, approval):
        return {
            "approval_id": approval.approval_id,
            "call_id": approval.call_id,
            "prompt": approval.prompt,
            "expires_at": approval.expires_at,
        }

    def prepare(self, session_id, call_id, name, arguments):
        with self.lock:
            session = self._session(session_id)
            self._prune()
            session.tools.validate(name, arguments)
            if name not in WRITE_TOOL_NAMES:
                raise ExecutorError(
                    400, "not_a_mutation", "Read tools do not need spoken approval."
                )
            fingerprint = json.dumps([name, arguments], sort_keys=True, allow_nan=False)
            old_id = self.active.get(session_id)
            if old_id:
                old = self._lookup(session_id, old_id)
                if old.state in {
                    "pending",
                    "armed",
                    "checking_prompt",
                    "classifying",
                    "executing",
                }:
                    if old.call_id == call_id and old.fingerprint == fingerprint:
                        return self._prepared(old)
                    if old.call_id == call_id and old.state != "executing":
                        self._reject(
                            old,
                            "rejected",
                            "The proposal changed. A new exact action requires fresh spoken approval.",
                        )
                        raise ExecutorError(
                            409,
                            "call_conflict",
                            "Changed arguments require a new action and spoken confirmation.",
                        )
                    raise ExecutorError(
                        409,
                        "approval_pending",
                        "Finish or cancel the current spoken confirmation before proposing another change.",
                    )
            prompt = confirmation_prompt(
                name, arguments, self.executor.settings.repository
            )
            receipt = self.executor.execute(session_id, call_id, name, arguments)
            error = json.loads(receipt["output"]).get("error")
            if (
                not isinstance(error, dict)
                or error.get("code") != "authorization_required"
            ):
                raise ExecutorError(
                    409,
                    "approval_consumed",
                    "This action already has a final outcome. Do not repeat it with a new ID without checking that outcome.",
                )
            approval = Approval(
                session_id,
                call_id,
                name,
                copy.deepcopy(arguments),
                fingerprint,
                secrets.token_urlsafe(24),
                prompt,
                int((self.wall_clock() + self.ttl) * 1000),
                self.clock() + self.ttl,
                boundary=self.timeline.get(session_id, 0),
            )
            self.approvals[approval.approval_id] = approval
            self.active[session_id] = approval.approval_id
            return self._prepared(approval)

    def _evidence(self, approval, events, expected):
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
            raise ExecutorError(
                400,
                "invalid_voice_evidence",
                "Supply bounded Live transcript evidence for this confirmation.",
            )
        fresh = []
        ids = set()
        seen = self.seen.setdefault(approval.session_id, set())
        last_start = -1
        text_length = 0
        for event in events:
            if not isinstance(event, dict) or event.get("type") != expected:
                raise ExecutorError(
                    400,
                    "invalid_voice_evidence",
                    "Only the expected Live transcript source can provide evidence.",
                )
            event_id, delta = event.get("event_id"), event.get("delta")
            start, end = event.get("start_ms"), event.get("end_ms")
            if (
                not isinstance(event_id, str)
                or not 1 <= len(event_id) <= 256
                or not isinstance(delta, str)
                or not delta
                or len(delta) > 4096
                or type(start) not in {int, float}
                or type(end) not in {int, float}
                or not math.isfinite(start)
                or not math.isfinite(end)
                or not 0 <= start <= end <= 86_400_000
                or start < last_start
            ):
                raise ExecutorError(
                    400,
                    "invalid_voice_evidence",
                    "Transcript IDs, text, and session timeline intervals must be valid and ordered.",
                )
            last_start = start
            text_length += len(delta)
            if text_length > MAX_TEXT:
                raise ExecutorError(
                    413,
                    "voice_evidence_too_large",
                    "Confirmation evidence is too long.",
                )
            if event_id in ids or event_id in seen or start < approval.boundary:
                continue
            ids.add(event_id)
            fresh.append(event)
        if not fresh:
            raise ExecutorError(
                409,
                "stale_voice_evidence",
                "A fresh spoken exchange is required; previous transcript evidence cannot be reused.",
            )
        if (
            len(seen) + len(ids)
            > self.executor.settings.max_calls_per_session * MAX_EVENTS * 2
        ):
            raise ExecutorError(
                429,
                "voice_evidence_limit",
                "Start a new session before more spoken confirmations.",
            )
        return fresh

    def _remember(self, approval, events):
        self.seen.setdefault(approval.session_id, set()).update(
            event["event_id"] for event in events
        )
        boundary = max(event["end_ms"] for event in events)
        approval.boundary = max(approval.boundary, boundary)
        self.timeline[approval.session_id] = max(
            self.timeline.get(approval.session_id, 0), boundary
        )

    def arm(self, session_id, approval_id, output_events, playback_finished):
        with self.lock:
            approval = self._lookup(session_id, approval_id)
            if approval.state == "armed":
                return {"armed": True, "input_after_ms": approval.boundary}
            if approval.state == "checking_prompt":
                return {
                    "armed": False,
                    "retryable": True,
                    "code": "prompt_check_running",
                    "message": "The spoken proposal is still being checked.",
                }
            if approval.state != "pending":
                raise ExecutorError(
                    409,
                    "approval_not_pending",
                    "This confirmation is no longer pending.",
                )
            if playback_finished is not True:
                return {
                    "armed": False,
                    "retryable": True,
                    "code": "prompt_not_finished",
                    "message": "Wait for the spoken question to finish.",
                }
            events = copy.deepcopy(
                self._evidence(
                    approval, output_events, "session.output_transcript.delta"
                )
            )
            text = "".join(event["delta"] for event in events)
            previous_boundary = approval.boundary
            approval.state = "checking_prompt"
            approval.generation += 1
            generation = approval.generation
        try:
            ready = self.language.prompt_ready(
                approval.name, copy.deepcopy(approval.arguments), text
            )
        except Exception:
            ready = False
        with self.lock:
            self._lookup(
                session_id, approval_id
            )  # Expiry/cancellation can win while classification runs.
            if approval.state != "checking_prompt" or approval.generation != generation:
                return {
                    "armed": False,
                    "retryable": False,
                    "code": "approval_not_pending",
                    "message": "This proposal is no longer waiting for a decision.",
                }
            if not ready:
                approval.state = "pending"
                return {
                    "armed": False,
                    "retryable": True,
                    "code": "prompt_not_observed",
                    "message": "Chatty is still describing the change or asking for approval.",
                }
            self._remember(approval, events)
            approval.boundary = prompt_input_boundary(events, previous_boundary)
            approval.state = "armed"
            approval.prompt_seen = True
            return {"armed": True, "input_after_ms": approval.boundary}

    def _reject(self, approval, status, message):
        receipt = self.executor.cancel_write(
            approval.session_id,
            approval.call_id,
            approval.name,
            approval.arguments,
            message,
        )
        approval.state = status
        result = {"status": status, "receipt": receipt, "message": message}
        approval.result.set_result(result)
        self.active.pop(approval.session_id, None)
        return result

    def _result(self, approval):
        try:
            return approval.result.result(
                timeout=self.executor.settings.duplicate_wait_seconds
            )
        except TimeoutError:
            raise ExecutorError(
                504,
                "tool_still_running",
                "The approved action is still running. Retry only this same approval ID to obtain its receipt.",
            ) from None

    def voice(self, session_id, approval_id, input_events, speech_finished, quiet_ms):
        try:
            attempt_key = hashlib.sha256(
                json.dumps(input_events, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
        except (ValueError, TypeError):
            raise ExecutorError(
                400, "invalid_voice_evidence", "Supply valid transcript evidence."
            ) from None
        with self.lock:
            approval = self._lookup(session_id, approval_id)
            if approval.state in {
                "executing",
                "approved",
                "rejected",
                "expired",
                "revision_requested",
            }:
                result = approval.result
                owner = False
            elif attempt_key in approval.attempts:
                result = approval.attempts[attempt_key]
                owner = False
            else:
                if approval.state not in {"armed", "classifying"}:
                    raise ExecutorError(
                        409,
                        "approval_not_armed",
                        "Wait until Chatty has finished asking for this confirmation.",
                    )
                if (
                    approval.attempts_started >= MAX_ATTEMPTS
                    or approval.checks_in_flight >= MAX_CLASSIFIERS
                ):
                    raise ExecutorError(
                        429,
                        "approval_check_limit",
                        "Too many simultaneous or repeated approval replies. Wait for the current reply or cancel this proposal.",
                    )
                if (
                    speech_finished is not True
                    or type(quiet_ms) not in {int, float}
                    or not math.isfinite(quiet_ms)
                    or not 1000 <= quiet_ms <= 90_000
                ):
                    raise ExecutorError(
                        400,
                        "speech_not_finished",
                        "Wait for input audio to end and at least one second of measured quiet.",
                    )
                events = copy.deepcopy(
                    self._evidence(
                        approval, input_events, "session.input_transcript.delta"
                    )
                )
                text = "".join(event["delta"] for event in events)
                approval.state = "classifying"
                approval.generation += 1
                generation = approval.generation
                result = Future()
                approval.attempts[attempt_key] = result
                approval.latest_reply = result
                approval.attempts_started += 1
                approval.checks_in_flight += 1
                owner = True
        if not owner:
            return self._wait_result(result)
        try:
            intent = self.language.reply_intent(
                approval.name, copy.deepcopy(approval.arguments), text
            )
        except Exception:
            intent = "unclear"
        finally:
            with self.lock:
                approval.checks_in_flight -= 1
        with self.lock:
            self._lookup(
                session_id, approval_id
            )  # Never execute stale consent after a slow classifier.
            if result.done():
                return (
                    result.result()
                )  # An explicit interruption invalidated this attempt.
            if approval.state != "classifying" or approval.generation != generation:
                successor = (
                    approval.result
                    if approval.state
                    in {
                        "approved",
                        "executing",
                        "rejected",
                        "expired",
                        "revision_requested",
                    }
                    else approval.latest_reply
                )
                execute = False
            elif intent == "reject":
                self._remember(approval, events)
                result.set_result(
                    self._reject(
                        approval,
                        "rejected",
                        "The proposed change was canceled by voice. No change was applied.",
                    )
                )
                return result.result()
            elif intent == "revise":
                self._remember(approval, events)
                outcome = self._reject(
                    approval,
                    "revision_requested",
                    "The participant requested a revision. Do not apply the old proposal; prepare the revised action and ask for approval.",
                )
                outcome["revision"] = text[:2000]
                output = json.loads(outcome["receipt"]["output"])
                output["revision_request"] = text[:2000]
                outcome["receipt"] = {
                    "call_id": approval.call_id,
                    "output": json.dumps(output),
                }
                result.set_result(outcome)
                return outcome
            elif intent != "approve":
                self._remember(approval, events)
                approval.state = "pending"
                approval.deadline = self.clock() + self.ttl
                approval.expires_at = int((self.wall_clock() + self.ttl) * 1000)
                outcome = {
                    "status": "ambiguous",
                    "message": "I didn't catch a clear decision. Should I go ahead with this change?",
                    "prompt": approval.prompt,
                    "expires_at": approval.expires_at,
                }
                result.set_result(outcome)
                return outcome
            else:
                self._remember(approval, events)
                approval.state = "executing"
                successor = None
                execute = True
        if not execute:
            outcome = self._wait_result(successor)
            with self.lock:
                if not result.done():
                    result.set_result(outcome)
                return result.result()
        try:
            receipt = self.executor.execute(
                approval.session_id,
                approval.call_id,
                approval.name,
                approval.arguments,
                approved=True,
            )
        except Exception:
            receipt = {
                "call_id": approval.call_id,
                "output": json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "approval_execution_uncertain",
                            "message": "The approved action did not return a confirmed receipt. Check GitHub before requesting it again.",
                            "uncertain": True,
                            "retryable": False,
                        },
                    }
                ),
            }
        with self.lock:
            approval.state = "approved"
            outcome = {"status": "approved", "receipt": receipt}
            approval.result.set_result(outcome)
            result.set_result(outcome)
            self.active.pop(approval.session_id, None)
        return outcome

    def _wait_result(self, future):
        try:
            return future.result(timeout=self.executor.settings.duplicate_wait_seconds)
        except TimeoutError:
            raise ExecutorError(
                504,
                "tool_still_running",
                "The current decision or approved action is still being handled. Retry only this same approval ID.",
            ) from None

    def interrupt(self, session_id, approval_id):
        """New speech invalidates a classifier, without canceling the proposal."""
        with self.lock:
            approval = self._lookup(session_id, approval_id)
            if approval.state in {"executing", "approved"}:
                return {"interrupted": False, "status": "executing"}
            if approval.state == "classifying":
                approval.generation += 1
                approval.state = "armed"
                invalidated = {
                    future for future in approval.attempts.values() if not future.done()
                }
                for previous in invalidated:
                    previous.set_result({"status": "interrupted"})
                approval.attempts = {
                    key: value
                    for key, value in approval.attempts.items()
                    if value not in invalidated
                }
                approval.latest_reply = None
            if approval.state == "pending" and approval.prompt_seen:
                # A clarification may finish just before this interruption arrives.
                # The same proposal was already described; keep its newer input
                # boundary, and let fresh continued speech decide it.
                approval.state = "armed"
                approval.generation += 1
            if approval.state == "armed":
                return {
                    "interrupted": True,
                    "armed": True,
                    "input_after_ms": approval.boundary,
                    "expires_at": approval.expires_at,
                }
            if approval.state == "pending":
                return {
                    "interrupted": True,
                    "armed": False,
                    "prompt": approval.prompt,
                    "expires_at": approval.expires_at,
                }
            return {"interrupted": False, "status": approval.state}

    def cancel(self, session_id, approval_id=None):
        with self.lock:
            self._session(session_id)
            approval_id = approval_id or self.active.get(session_id)
            if not approval_id:
                return {"status": "rejected", "message": "No pending change remains."}
            approval = self._lookup(session_id, approval_id)
            if approval.state in {"pending", "armed", "checking_prompt", "classifying"}:
                return self._reject(
                    approval,
                    "rejected",
                    "The pending spoken confirmation was canceled. No change was applied.",
                )
            if approval.state == "executing":
                return {
                    "status": "approved",
                    "message": "This change was already approved and started; it may still complete. Check its receipt before retrying.",
                }
            return self._result(approval)
