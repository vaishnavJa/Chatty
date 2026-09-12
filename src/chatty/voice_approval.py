"""Action-bound spoken approval for the trusted, same-origin localhost client.

The browser relays Live transcript envelopes and measured playback/input activity.
These are not independently authenticated server events or speaker identification.
Speech segmentation is heuristic; anyone audible in the meeting can answer. This
module prevents stale/model-output evidence and changed proposals in the normal
client flow, but cannot detect fabricated browser evidence or acoustic replay.
Only bounded evidence for the current confirmation is retained, never a meeting.
"""

import copy
import json
import math
import re
import secrets
import threading
import time
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field

from chatty.agents.tools import TOOL_CAPABILITIES, WRITE_TOOL_NAMES
from chatty.integrations.gpt_live.executor import ExecutorError

MAX_EVENTS = 128
MAX_TEXT = 16_384


def normalize(text):
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


def _number_words(value):
    small = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
    if value < 20:
        return small[value]
    if value < 100:
        return tens[value // 10] + (" " + small[value % 10] if value % 10 else "")
    if value < 1000:
        return (
            small[value // 100]
            + " hundred"
            + (" " + _number_words(value % 100) if value % 100 else "")
        )
    if value < 1_000_000:
        return (
            _number_words(value // 1000)
            + " thousand"
            + (" " + _number_words(value % 1000) if value % 1000 else "")
        )
    return str(value)


def normalize_prompt(text):
    # Speech often spells numbers and punctuation. This only normalizes prompt
    # evidence; approval command classification keeps its strict whole utterance.
    text = re.sub(
        r"\b\d+\b",
        lambda match: _number_words(int(match[0])) if len(match[0]) < 7 else match[0],
        text,
    )
    text = re.sub(r"\b(?:slash|dot|colon)\b", "", text, flags=re.I)
    return normalize(text).replace(" ", "")


def confirmation_prompt(name, arguments, repository):
    """Describe every supplied field; explicitly identify drafts too long to read."""
    target = (
        "the configured GitHub project"
        if "project" in name
        else "the Chatty repository"
    )
    label = TOOL_CAPABILITIES[name]["label"]
    parts = [f"Proposed change: {label} in {target}."]
    for key, value in arguments.items():
        rendered = (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )
        rendered = " ".join(rendered.split())
        if key in {"sha", "expected_sha", "expected_head_sha"}:
            rendered = "the exact previously read revision"
        elif len(rendered) > 100:
            rendered = (
                f"the prepared {len(rendered)} character draft; full text in the app"
            )
        parts.append(
            f"{key.replace('_', ' ')}: {rendered or 'empty; clear this field'}."
        )
    if TOOL_CAPABILITIES[name]["destructive"]:
        parts.append(
            "This operation can remove data, merge code, or run workflow effects."
        )
    prompt = " ".join(parts) + " Do you approve this change?"
    # Never silently omit fields from a confirmation to meet a model token limit.
    if len(prompt) > 650:
        raise ExecutorError(
            400,
            "proposal_too_long",
            "Split this change into smaller actions so Chatty can describe each one before spoken approval.",
        )
    return prompt


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


class VoiceApprovals:
    def __init__(self, executor, *, clock=time.monotonic, wall_clock=time.time, ttl=90):
        self.executor = executor
        self.clock = clock
        self.wall_clock = wall_clock
        self.ttl = ttl
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
        if approval.state in {"pending", "armed"} and self.clock() >= approval.deadline:
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
                if old.state in {"pending", "armed", "executing"}:
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
                return {"armed": True}
            if approval.state != "pending":
                raise ExecutorError(
                    409,
                    "approval_not_pending",
                    "This confirmation is no longer pending.",
                )
            if playback_finished is not True:
                raise ExecutorError(
                    400,
                    "prompt_not_finished",
                    "Wait for the actual confirmation prompt playback to finish.",
                )
            events = self._evidence(
                approval, output_events, "session.output_transcript.delta"
            )
            text = normalize_prompt("".join(event["delta"] for event in events))
            if normalize_prompt(approval.prompt) not in text:
                raise ExecutorError(
                    409,
                    "prompt_not_observed",
                    "Chatty must speak the complete proposed change before accepting confirmation.",
                )
            self._remember(approval, events)
            approval.state = "armed"
            return {"armed": True}

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
        with self.lock:
            approval = self._lookup(session_id, approval_id)
            if approval.state not in {"pending", "armed"}:
                owner = False
            else:
                if approval.state != "armed":
                    raise ExecutorError(
                        409,
                        "approval_not_armed",
                        "Wait until Chatty has finished asking for this confirmation.",
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
                events = self._evidence(
                    approval, input_events, "session.input_transcript.delta"
                )
                self._remember(approval, events)
                text = normalize("".join(event["delta"] for event in events))
                text = re.sub(r"^(?:hey )?chatty\s+", "", text)
                positive = {
                    "yes",
                    "yes please",
                    "yes do it",
                    "yes go ahead",
                    "yes i approve",
                    "yes approve",
                    "approve",
                    "approved",
                    "i approve",
                    "confirm",
                    "confirmed",
                    "go ahead",
                    "do it",
                    "please do it",
                }
                negative = {
                    "no",
                    "no thanks",
                    "no thank you",
                    "no dont",
                    "no dont do it",
                    "dont do it",
                    "do not do it",
                    "cancel",
                    "cancel it",
                    "cancel this",
                    "cancel this change",
                    "stop",
                    "pause",
                    "be quiet",
                    "reject",
                    "reject it",
                    "never mind",
                    "nevermind",
                }
                if text in negative:
                    return self._reject(
                        approval,
                        "rejected",
                        "The proposed change was canceled by voice. No change was applied.",
                    )
                if text not in positive:
                    return self._reject(
                        approval,
                        "ambiguous",
                        "That response was not an unambiguous approval. Clarify the request and propose a new exact change before asking again.",
                    )
                approval.state = "executing"  # Consume before releasing the lock.
                owner = True
        if owner:
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
                approval.result.set_result({"status": "approved", "receipt": receipt})
                self.active.pop(approval.session_id, None)
        return self._result(approval)

    def cancel(self, session_id, approval_id=None):
        with self.lock:
            self._session(session_id)
            approval_id = approval_id or self.active.get(session_id)
            if not approval_id:
                return {"status": "rejected", "message": "No pending change remains."}
            approval = self._lookup(session_id, approval_id)
            if approval.state in {"pending", "armed"}:
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
