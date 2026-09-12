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
Restart after changing `.env`. `OPENAI_BACKEND_MODEL` must name a Responses model
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

{"session_id":"<connection.sessionId>","call_id":"<original call_id>","name":"create_issue","arguments":{"title":"<title>","body":"<body>"}}
```

`arguments` is a **parsed JSON object**, following the tool owner's published
schema. Do not forward the raw arguments JSON string or add authorization fields
that the tool schema does not declare.

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

Stop must mute locally even while HTTP is pending. It does not undo or cancel a
running GitHub call. Preserve its receipt, and do not re-arm speech just because a
tool completed. The backend's initial voice prompt starts silently and instructs
Chatty to respond to its name; the UI still owns enforceable wake/playback policy.

## GitHub owner: module contract

Export `TOOL_SCHEMAS` and `execute_tool(name, arguments)` from
`chatty.agents.tools`. The backend accepts either a synchronous or asynchronous
function and a JSON-serializable return value (or a valid JSON string).

Schemas use `{type:'function',name,description,parameters,strict?}` with object
parameters. They are inserted unchanged under
`session.delegation.responses.tools`. The allowed names are:
`list_recent_commits`, `list_open_pull_requests`, `list_open_issues`, `create_issue`.
The server validates arguments using those schemas before calling the module.
The module must enforce repository scope and its own bounded remote-operation
timeouts; it must not retry an uncertain write automatically.

There is **one** server-owned executor. Concurrent duplicates reserve
`(session_id, call_id)` before execution; repeats return the same receipt. Changed
arguments with the same ID get 409. Failures are cached too. Receipts live in
memory for that local session, up to two hours; restarting rejects old sessions.
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

The agreed four-field execution contract contains no transcript or approval
proof. The backend cannot independently attest that a request was spoken. The
trusted browser must dispatch only authorized requests; the voice/backend prompts
require an explicit request and the GitHub module must treat repository text as
data. This is a local trusted-operator demo, not a multi-user approval service.

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
