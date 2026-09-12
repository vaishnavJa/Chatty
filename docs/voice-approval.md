# Natural conversation and spoken approval

Say **Chatty** once to begin a conversation. Follow-up questions and commands do
not need its name again. Chatty stays active through pauses and completed answers
until **Chatty, stop**. That phrase cuts off remote speech, plays one brief local
**Okay**, and leaves input listening for the next wake word. The Stop button mutes
silently. The bundled acknowledgment uses a different voice from Live.

All 17 supported repository and project mutations use a saved proposal and spoken
approval. Keep the app open for its audio connection; no approval click is needed.

1. Ask **“Create an issue for saving meeting summaries with decisions and owners.”**
2. Chatty asks a short question such as **“Should I create that meeting-summary
   issue?”** It does not read the full title, body or field list.
3. Reply naturally: **“Yes, go ahead,” “That sounds good,”** or an equivalent clear
   instruction to carry out the proposal. **No** or **cancel** declines it.
4. If your reply is unclear, Chatty asks a brief clarification and keeps the same
   saved action pending. If you ask to change the action, it prepares a revised
   proposal and obtains fresh approval.
5. Chatty reports success only after the actual tool receipt confirms it. The app
   shows the saved payload and returned link or error for optional inspection.

These examples create a real issue only after approval; choose a deliberate demo
issue for live rehearsal. Reads need no confirmation. Approval covers the complete
saved payload, not only the brief spoken summary. Only one proposal is pending at
a time. Its confirmation window lasts 90 seconds and renews after clarification;
this expiration never puts an otherwise active conversation to sleep.

## Application and backend contract

The browser is the sole Live function dispatcher. A mutation function call proposes
an action rather than authorizing it. Once the explicit request is clear, Live's
backend emits the concrete tool arguments immediately. The application supplies
one short confirmation question and collects the answer. The conversational model
must not independently grant approval, add approval fields to tool arguments or
create another mutation call merely because the participant answered yes.

All routes use same-origin localhost JSON POSTs. Opaque session/call IDs remain
unchanged. Approval IDs and transcript evidence belong to the application.

| Endpoint | Request fields | Result |
| --- | --- | --- |
| `/api/approvals/prepare` | `session_id`, `call_id`, `name`, `arguments` | `approval_id`, `call_id`, short `prompt`, `expires_at` in epoch milliseconds |
| `/api/approvals/arm` | `session_id`, `approval_id`, `output_events`, `playback_finished: true` | `armed` and `input_after_ms` when ready; incomplete speech returns retryable `armed: false` |
| `/api/approvals/voice` | `session_id`, `approval_id`, `input_events`, `speech_finished: true`, `quiet_ms` | Terminal receipt or a nonterminal clarification/interruption |
| `/api/approvals/interrupt` | `session_id`, `approval_id` | Invalidates pending interpretation while retaining the same proposal; an already executing write cannot be interrupted |
| `/api/approvals/cancel` | `session_id`, optional `approval_id` | Cancellation status and any available receipt |

`prepare` validates the registered schema and saves an immutable copy of the exact
arguments. A short summary identifies the action, target and topic. The summary
omits the full draft and internal fields; the saved payload remains available in
the app. Changing arguments under the same call ID conflicts.

`arm` checks fresh `session.output_transcript.delta` evidence plus the browser's
playback-finished signal. The spoken wording may vary: it must describe the pending
action and ask for consent, rather than match an exact string. An incomplete prompt
keeps the proposal pending for more evidence. Instruction acknowledgment and
`response.completed` alone do not establish that the question was spoken.

`voice` considers fresh `session.input_transcript.delta` envelopes containing
`event_id`, `delta`, `start_ms` and `end_ms`. The browser waits for measured input
quiet and settled captions. Server-provided `input_after_ms` allows a short reply
to overlap the end of the consent question by up to 750 ms; earlier speech or
reused evidence cannot authorize the action. A fragment containing yes is not
executed while the same reply is still being accumulated.

Common clear replies have a local interpretation path. Other wording is classified
against the saved proposal by a bounded, no-tools Responses request using the
existing configured backend model and key. A strict JSON schema constrains the
classification. It uses a five-second HTTP timeout and may add latency; this is
not a guarantee of total response time. Refusal, malformed output, timeout or uncertainty never authorizes
a mutation. The classifier cannot edit the saved payload or execute tools.
Repository text, draft content and screenshots remain data, not approval.

A clear approval executes the saved action once through the existing durable
ledger. `approved`, `rejected`, `revision_requested` and `expired` outcomes provide
a `{call_id, output}` receipt; inspect its JSON-string `output` to learn whether
GitHub succeeded. `revision_requested` includes the requested amendment so Live
can clarify and propose a new call with fresh approval. No old approval transfers
to the revised action.

`ambiguous` returns a short clarification `prompt`, `message` and renewed
`expires_at`, without a tool receipt. Keep the same immutable action, speak the
clarification, re-arm and collect a fresh answer. Do not report the function as
completed or cancel it merely because the first reply was unclear.

If the participant continues speaking during interpretation, `interrupt` invalidates
that classification generation without canceling the proposal. The old voice
request returns `interrupted` without a receipt. The browser accumulates the
continued reply and submits it when settled. If interruption returns `armed: false`, speak the supplied
prompt and re-arm before submitting; `armed: true` includes the renewed
`input_after_ms` and `expires_at` for the continued reply. Already executing writes
return `interrupted: false`. Stop or explicit cancellation ends a
pending proposal; late classifier results cannot authorize it afterward. Once a
GitHub request is executing, neither interrupt nor Stop can undo it. Keep its
receipt even if playback stays muted.

Submit final receipts unchanged as Live `function_call_output` items and continue
a delegated response only after all required results are supplied. The old HTTP
`approved: true` flag on `/api/tools/execute` is not authority for a write. No
sideband executor or model-supplied approval flag exists. Keep the persistent
GitHub ledger across restarts and never retry an uncertain write with a new ID.

## Trust, timing and deployment

The localhost server trusts our browser's relayed provider events and audio-activity
claims. It does not independently authenticate a speaker, prove that a question
was heard, or detect fabricated browser evidence or acoustic replay. Anyone audible
in the meeting can answer a pending proposal. Host/Origin checks protect the web
boundary, not participant identity.

Live has no authoritative transcript-turn-completed event. Quiet and caption-settle
windows are practical heuristics; long pauses, overlapping speech, delayed captions
and recognition errors can still affect decisions. Natural-language interpretation
is also fallible. This does not promise flawless consent detection or speaker
authentication. Keep the virtual microphone isolated from captured meeting audio;
Chatty must not present its screen.

Changes require a fresh server and Live session. Editing files does not change
prompts or code already loaded in the running meeting. Isolated mocked tests cover
request boundaries, saved payloads, natural decisions, clarification, interruption,
replay, cancellation and acknowledgment routing. They make no real OpenAI/GitHub
calls and do not open microphones. Real meeting wake/follow-ups, the audible Okay,
natural confirmation and exactly one GitHub receipt still need a live rehearsal.

See [meeting setup](meeting-setup.md) for the voice-only audio route and
[capabilities](capabilities.md) for repository and project scope.

Implementation references:
[Live delegation and function results](https://developers.openai.com/api/docs/guides/live-delegation),
[Live transcript and playback semantics](https://developers.openai.com/api/docs/guides/live-conversations),
and [Structured Outputs and refusal handling](https://developers.openai.com/api/docs/guides/structured-outputs).
