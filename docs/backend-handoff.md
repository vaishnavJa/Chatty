# Live backend handoff (issue #7)

This branch implements the laptop server. It does not change `web/`, the GitHub
implementation, or the tool owner's `src/chatty/agents/tools.py`.

## Start

Install Python 3.12+ and uv. From the repository root:

```sh
uv sync --locked
# Copy .env.example to .env and fill OPENAI_API_KEY locally.
uv run chatty
```

Open **http://localhost:3000**. `python -m chatty` is the equivalent installed
entry point. `CHATTY_PORT` changes the port; binding stays on `127.0.0.1`.
Start a fresh server and Live session after changing `.env`, prompts or dialogue
policy; a running session keeps its original configuration. `OPENAI_BACKEND_MODEL` must name a Responses model
available to your API project (default: `gpt-5.6-terra`). Voice uses `gpt-live-1`.
The API key never goes to the browser. No SDK version with Live support is needed:
the integration sends the documented HTTP request directly.

`GET /api/health` reports configuration/module/UI readiness, **not** API access or
a successful audio test. Before the UI lands, `/` displays a backend-ready page.
Once `web/index.html` exists, it and its assets are served at `/` and `/app.js`, etc.
`CHATTY_WEB_DIR` can point to a teammate's existing UI checkout for local testing.

## Audio owner: session contract

```http
POST /api/live/session
Content-Type: application/json
Origin: http://localhost:3000

{"sdp":"<browser localDescription.sdp after ICE gathering>"}
```

Success: **201** (use `response.ok`, not a check for only 200).

```json
{
  "session": {"id": "<opaque OpenAI session ID>"},
  "transport": {"type": "webrtc", "sdp": "<exact SDP answer>"}
}
```

Retain `session.id` on `connection.sessionId`. Apply the answer and wait for
`session.started` before sending commands. The server uses
`POST https://api.openai.com/v1/live/sessions` with JSON `{session, transport}`;
it does not use Realtime calls, ephemeral keys, or `session.start`.

## UI owner: tool execution contract

The browser is the **only** Live function-event dispatcher. Collect completed
function items from `response.event` → `event.type == response.output_item.done`.
Only dispatch actual function items with the original `call_id`.

```http
POST /api/tools/execute
Content-Type: application/json
Origin: http://localhost:3000

{"session_id":"<connection.sessionId>","call_id":"<original call_id>","name":"list_open_issues","arguments":{}}
```

`arguments` is a **parsed JSON object**, following the tool owner's published
schema. Do not forward the raw arguments JSON string or add authorization fields
inside it. Reads use this four-field interface. All mutation tools instead enter
the application's [spoken approval protocol](voice-approval.md): prepare the exact
call through `/api/approvals/prepare`, speak the short action summary and natural
confirmation question, arm it with playback and semantic prompt evidence, and
submit the fresh spoken answer to
`/api/approvals/voice`. No browser approval click is needed. The server returns the
original call's receipt after approval, rejection, requested revision or expiry.
An ambiguous answer returns a clarification prompt without a receipt; retain the
same saved action, speak the short clarification and collect a fresh reply.
The backend accepts meaning-based consent rather than requiring a fixed phrase.
Questions about the saved draft return nonterminal `question` with `answer`,
`details`, a consent `prompt` and a renewed expiry. Speak that answer and prompt,
re-arm, and wait for fresh consent; do not complete the original function call.
Answers use the saved fields, with explicit spoken excerpts for long values.
Readiness failures may return retryable `prompt_retry_required`; use its saved
canonical prompt within the browser's bounded retry allowance rather than
canceling a useful draft or treating a failed check as permission.

The legacy top-level `approved: true` on `/api/tools/execute` is not authority to
write. A direct write returns `authorization_required` without executing. Only the
approval manager can execute its saved payload after voice confirmation. The
model proposes concrete arguments immediately once the request is clear; the
application owns the spoken approval question so the model must not ask it twice.

Success or a completed tool-level failure: **200**, always the same outer shape:

```json
{"call_id":"<original call_id>","output":"{\"number\":42,\"url\":\"https://github.com/vaishnavJa/Chatty/issues/42\"}"}
```

This is a shape example, not a real created issue. Tool result fields inside
`output` are owned by issue #9. `output` is already a JSON string: pass it unchanged
to `response.item.create` → `item: {type:'function_call_output', call_id, output}`.
After all required results are submitted, send bare `response.create`.

HTTP/request failures use `{"error":"safe message","code":"stable_code"}`.
Examples: 400 `invalid_arguments` / `unknown_tool`, 404 `unknown_session`,
409 `call_conflict`, 503 `tools_unavailable`, 504 `tool_still_running`.
Do not treat an HTTP error body as a successful function receipt. For
`tool_still_running`, a retry with the **same** session/call/arguments waits for the
original result. Never generate a new call ID to retry a possibly completed write.

An unexpected tool exception produces a cached 200 receipt whose output is:

```json
{"ok":false,"error":{"code":"tool_execution_failed","message":"The tool did not return a confirmed result. Check GitHub before requesting the action again.","retryable":false}}
```

Stop must mute locally even while HTTP is pending and cancel an unexecuted voice
proposal through `/api/approvals/cancel`. It does not undo or cancel a running
GitHub call. Preserve its receipt, and do not re-arm speech just because a tool
completed. After a wake word, Chatty stays active for follow-up questions and
commands until explicit Stop; no answer-completed or quiet timer mutes it.
The UI owns the single local **Okay** acknowledgment for spoken **Chatty, stop**
while remote output remains muted; the Stop button is silent. Input stays enabled
for the next wake word.

## Current-session discussion evidence

The browser relays actual participant transcript events to
`POST /api/meeting/context` with `session_id`, `events`, `batch_sequence` and
optional `dropped_before`. Each batch contains at most 32 exact
`session.input_transcript.delta` envelopes with `event_id`, `delta`, `start_ms`
and `end_ms`; assistant transcripts are not accepted. Sequence and event replay
checks preserve source fragments instead of merging repeated words heuristically.

`read_meeting_context` uses the normal tool route after the browser flushes its
relay. It returns a fresh bounded snapshot rather than a cached old transcript.
`POST /api/meeting/context/end` accepts only `session_id`, clears the store and
prevents late packets from repopulating that context. Stop is different from End:
it leaves input listening and context collection active.

The server buffer and browser relay are bounded; the existing UI transcript is
a separate in-memory collection. See [capabilities](capabilities.md) for retention,
output-budget and source limitations. Context is data, not consent or a claim of
verified speakers or group agreement.

## GitHub owner: module contract

Export `TOOL_SCHEMAS` and
`execute_call(session_id, call_id, name, arguments, *, explicit_user_request, ledger)`
from `chatty.agents.tools`. Production uses this adapter and its durable GitHub
ledger. Two-argument synchronous/asynchronous runners are supported for injected
offline fixtures only.

Schemas use `{type:'function',name,description,parameters,strict?}` with object
parameters. They are inserted unchanged under
`session.delegation.responses.tools`. The current 34-tool registry and its 17
mutations are listed in [capabilities.md](capabilities.md).
The server validates arguments using those schemas before calling the module.
The module must enforce repository scope and its own bounded remote-operation
timeouts; it must not retry an uncertain write automatically.

There is **one** server-owned executor. Concurrent duplicates reserve
`(session_id, call_id)` before execution; repeats return the same receipt. Changed
arguments with the same ID get 409. Completed failures are cached too; an
authorization-required response leaves a bound call pending human approval.
Session receipts live in memory for up to two hours, and write reservations and
results persist in `.chatty/github-ledger.sqlite3` (override with
`CHATTY_GITHUB_LEDGER_PATH`). Keep that ledger across restarts. Restarting rejects old sessions.
Do not replay old calls into a newly created session. No sideband tool executor.

If the module is absent, Live can connect with no tools for early audio testing;
health explicitly reports `not_installed`. Broken modules fail session creation
with `invalid_tool_module`. Modules are loaded for each new session; existing
sessions retain their original tool schemas. Test fixtures are injected only in
tests, never returned as real GitHub data.

## Local trust and authorization

Use the page served by this process. POSTs require a matching localhost Host and
Origin, JSON, and a body of at most 64 KiB. No cross-origin CORS or LAN binding.
These checks prevent browser cross-site writes; they do not authenticate the
local machine's owner. Do not tunnel or reverse-proxy this demo onto the internet.

The same-origin browser relays original Live transcript events and measured audio
activity for the saved proposal and fresh voiced answer. The server validates
this evidence and consumes the proposal once. It does not independently attest
speaker identity, acoustic origin or complete speech turns. Live has no
authoritative transcript-turn-done event, so input quiet and settled captions are
heuristics. Voice/backend prompts require an explicit request, and the GitHub
module treats repository text as data. This is a local trusted-operator demo. See
[voice-approval.md](voice-approval.md) for the full approval and replay contract.

## Verification

```sh
uv run pytest tests/backend
uv run ruff check .
uv run ruff format --check .
```

Fixtures cover the exact OpenAI HTTP shape, redacted errors, startup without a
key/module/UI, imported schema validation, concurrency, uncertain writes, and
localhost/static-file boundaries. They do not establish live audio acceptance.

With the audio/UI branches integrated and a key with model access, verify a real
SDP exchange, `session.started`, input speech, audible output, then Stop/Resume.
Record the result explicitly. Real GitHub writes require a deliberately requested
demo issue, coordinated with issue #9; do not create one just to probe credentials.

Sources:
- https://developers.openai.com/api/docs/guides/voice-webrtc?api=live
- https://developers.openai.com/api/reference/resources/live/methods/create
- https://developers.openai.com/api/docs/guides/live-delegation
