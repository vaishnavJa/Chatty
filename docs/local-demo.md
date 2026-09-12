# Run the integrated demo locally

From the repository root, run `uv run chatty`, then open
`http://localhost:3000` in Chrome. To use a different port, launch with
`CHATTY_PORT=8765 uv run chatty`. The server always binds to `127.0.0.1`.
The API and browser assets share the same origin.

Set `OPENAI_API_KEY` in the ignored root `.env` or the server environment.
`OPENAI_BACKEND_MODEL` defaults to `gpt-5.6-terra`; the voice model is
`gpt-live-1`. GitHub tools use the existing authenticated GitHub CLI or supported
token environment variables and are restricted to `vaishnavJa/Chatty`.
Credentials stay on the server. `GET /api/health` reports configuration flags.

Start with microphone input and headphones. Click Start, allow the microphone,
and say “Hey Chatty, what changed recently in this repository?” Check the spoken
answer and its source links. A real OpenAI session starts only after Start;
starting the HTTP server does not create one. End the session after testing.
Follow `docs/meeting-setup.md` for the subsequent meeting-tab audio test.

## Confirm an issue

Ask Chatty for a specific issue, review its exact title and body in the page,
and click **Create issue**. The app sends
`POST /api/tools/execute` with:

```json
{
  "session_id": "the-session-returned-by-this-server",
  "call_id": "the-original-live-function-call-id",
  "name": "create_issue",
  "arguments": {"title": "Reviewed title", "body": "Reviewed body"},
  "approved": true
}
```

The top-level `approved` field must come from that human click. It is optional
for reads, which retain the four-field interface. Model arguments cannot supply
approval. An unapproved write returns an `authorization_required` tool receipt
without creating an issue. Its call ID remains bound to the same tool and exact
arguments, allowing later approval of the reviewed payload. Changing the title,
body or tool under that call ID returns `call_conflict`.

The response remains `{ "call_id": "…", "output": "JSON string" }`.
The browser sends the output as a Live `function_call_output` for the original
call ID. Successful writes include the actual issue URL. Stop immediately mutes
playback in the browser; it cannot undo an issue already created.

The production adapter uses the GitHub module's `execute_call` and durable
SQLite ledger at `.chatty/github-ledger.sqlite3`. An explicit
`CHATTY_GITHUB_LEDGER_PATH` can choose another persistent file. Do not remove this
ledger during a demo or retry an uncertain write with a new call ID. A replay
with the same session, call ID and arguments returns its recorded result.
Server restarts require a new Live session; an old session ID is not accepted
unless registered again by the server.

This is a single-user localhost demo. Host, Origin, schema, session and call-ID
checks protect its browser boundary; another program running as the same OS
user remains trusted. Do not expose it through a public tunnel. Capturing and
returning audio in a real meeting still needs a live end-to-end rehearsal.
