# Approve GitHub changes by voice

All 17 supported repository and project mutations use spoken approval. Keep the
Chatty app open for its audio connection; nobody needs to click an approval button.

1. Say **“Chatty, create an issue titled Demo follow-up with body Review the demo.”**
2. Chatty prepares the change and reads its operation, destination and supplied
   fields aloud, ending with **“Do you approve this change?”**
3. After it finishes, say **“Yes”** or **“Chatty confirm.”** Say **“No,” “Chatty
   cancel,”** or **“Chatty, stop”** to cancel instead.
4. Wait for the result. Chatty reports success only after GitHub returns a receipt;
   the app also shows the actual link or error.

The example creates a real issue only after approval. Use a deliberately chosen
demo issue when rehearsing. Reads need no approval. The confirmation question and
answer are part of one addressed request, so a pending “yes” needs no extra wake
word. After completing that request, Chatty returns to quiet listening.

Only one proposal can wait for approval at a time. It expires 90 seconds after
preparation. A changed or ambiguous answer cancels that proposal: clarify what you
want and Chatty will prepare a fresh one. Silence, an unrelated “yes,” assistant
speech, repository content and screen content do not approve a pending change.

The complete arguments are saved before Chatty asks. Long text fields are announced
as prepared drafts with their character lengths; the full draft remains visible
in the app for optional inspection. Saying yes approves that complete saved draft,
including text not read aloud. Ask for a smaller change if every word must be read
aloud. The proposal is rejected if its spoken description exceeds the bounded
prompt size rather than silently dropping fields. Changed arguments always need
fresh approval.

## Application and backend contract

The browser remains the sole Live function dispatcher. A mutation function call
**proposes** the action; it does not authorize execution. Live and its delegated
backend emit concrete tool arguments once the user request is clear. They do not
ask for approval independently before emitting that call. The application then
requests one spoken confirmation and handles the answer itself.

All requests below are same-origin JSON POSTs to the localhost server. The app
keeps opaque session and function call IDs unchanged. Approval IDs and evidence
belong to the application, never to model tool arguments.

| Endpoint | Request fields | Result |
| --- | --- | --- |
| `/api/approvals/prepare` | `session_id`, `call_id`, `name`, `arguments` | `approval_id`, `call_id`, `prompt`, `expires_at` (epoch milliseconds) |
| `/api/approvals/arm` | `session_id`, `approval_id`, `output_events`, `playback_finished: true` | `armed: true` |
| `/api/approvals/voice` | `session_id`, `approval_id`, `input_events`, `speech_finished: true`, `quiet_ms` | `status`, `receipt`, optional `message` |
| `/api/approvals/cancel` | `session_id`, optional `approval_id` | Cancellation status and any available receipt |

`prepare` validates the registered tool schema and binds the exact arguments to
the session and original call ID. The saved copy is the only payload that can be
executed. Reusing that call ID with changed arguments conflicts; an unresolved
proposal blocks a second one in the same session. The generated `prompt` names
the operation, destination and supplied fields and ends with the approval question.

`arm` requires the original `session.output_transcript.delta` envelopes containing
the complete proposal and question, plus the browser's playback-finished signal.
Case, punctuation, spacing and spoken-number differences are normalized. It does
not arm from `response.completed`, a successful instruction acknowledgment, a
question fragment, or a backend result. The browser waits for measured output
audio to become quiet before claiming playback has finished.

`voice` uses original `session.input_transcript.delta` envelopes for a fresh answer
after the spoken prompt. Each event retains `event_id`, `delta`, `start_ms` and
`end_ms`. Event IDs and intervals are checked for freshness and reuse. Only the
whole accumulated utterance is classified: **yes**, **confirm**, **approve**,
**go ahead**, and simple variants can approve, with an optional **Chatty** prefix.
**No**, **cancel**, **stop**, and their supported variants reject. A positive word
inside a longer amendment or unrelated sentence does not approve.

The browser waits for measured input audio to finish, at least one second of
input quiet, and transcript text to settle before submitting. No partial “yes”
fragment may execute a tool. `status` is `approved`, `rejected`, `ambiguous` or
`expired`; completed states include the original `{call_id, output}` receipt,
where `output` is already a JSON string. Submit that receipt unchanged as the
Live `function_call_output`, then continue only when all required results have
been provided. Approval success means the action was authorized; inspect the
receipt to determine whether GitHub actually succeeded.

`cancel` terminates a pending proposal. It can be called without an approval ID
to cancel the session's current proposal during Stop or session cleanup. Stopping
after execution has started cannot undo the GitHub request; retain its eventual
receipt and keep playback muted. A finished approval ID is consumed once and
duplicate requests return the same result. The existing durable GitHub ledger
protects write reservations and receipts across restarts. Never remove that ledger
or retry an uncertain write using a new call ID.

`/api/tools/execute` continues to handle reads. Its legacy top-level `approved:
true` is no longer authority for a write; writes must pass through the approval
manager. The manager calls the existing executor with its saved payload after
spoken confirmation. No sideband executor or model-supplied approval flag exists.

## Trust and timing limits

This is a trusted localhost demonstration. The server validates transcript
envelopes relayed by our browser and that browser's audio-activity claims. It does
not independently obtain the provider stream, authenticate a speaker, or prove
that audio was heard. Anyone audible in the meeting can answer a pending question.
Fabricated browser evidence, acoustic replay and speech-recognition errors are
outside that trust boundary. Host and Origin checks do not authenticate individual
meeting participants.

Live transcript deltas have no authoritative user-turn-completed event. Audio
quiet and settled-text windows are application heuristics, so a long pause before
a correction can be mistaken for the end of a response. They need a real meeting
rehearsal with delayed captions, interruptions and overlapping speech. This is
not a guarantee of complete utterance recognition or speaker authorization.

Keep Chatty's microphone input and voice output isolated using the
[voice-only meeting setup](meeting-setup.md). Chatty must not present its screen.
Optional incoming screen context supplies requested snapshots and never grants
authorization for a change.

## Verification

Offline backend and browser tests exercise proposals, fresh and stale evidence,
whole-utterance confirmation, denial, ambiguity, expiry, duplicate requests,
changed payloads, Stop, session teardown and all supported mutation paths. Tests
use fake providers and GitHub calls; they do not create live issues.

After restarting the server and starting a fresh Live session, rehearse an
explicitly requested disposable issue: hear the proposal, answer yes, and verify
exactly one GitHub receipt. Rehearse no and “Chatty, stop” before confirming a
second proposal and verify that neither creates an issue. Hearing these phrases
through real Meet audio remains separate evidence from automated test results.

Primary API references:
[Live delegation and function results](https://developers.openai.com/api/docs/guides/live-delegation),
[Live transcript and playback semantics](https://developers.openai.com/api/docs/guides/live-conversations).
