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

After the first **Chatty**, follow-up questions and commands need no wake word.
Chatty remains active through pauses and completed answers until **Chatty, stop**.
Stop mutes remote speech, plays a brief local **Okay**, and keeps input listening.
Start a fresh server and Live session to load changed prompts and dialogue policy;
an existing call keeps the configuration it started with.

## Confirm an issue by voice

Say “Chatty, create an issue” with the title and body you want. Chatty prepares the
exact change and asks a short, natural question about the action and topic. It
does not recite the full draft or field list. Say **Yes, go ahead**, or give an
equivalent reply in your own words. Say **No**, **cancel**, or **Chatty, stop** to
cancel. No approval button is required. The full saved
payload and resulting receipt remain visible in the app.

This applies to all supported repository and project mutations. The server's
`/api/approvals/prepare`, `arm`, `voice` and `cancel` routes bind confirmation to a
specific session, call ID and saved payload. The old `approved: true` flag on
`/api/tools/execute` cannot authorize a write. Model arguments cannot supply
approval. Confirmation windows expire after 90 seconds; an unclear answer keeps
the same action pending, asks a brief clarification and renews that window. A
changed action requires a revised proposal and fresh approval. See
[voice-approval.md](voice-approval.md) for accepted answers, long-draft behavior,
event freshness and the exact API contract.

The response remains `{ "call_id": "…", "output": "JSON string" }`.
The browser sends the output as a Live `function_call_output` for the original
call ID. Successful writes include the actual issue URL. Stop immediately mutes
playback and cancels an unexecuted proposal; it cannot undo an issue already created.

The production adapter uses the GitHub module's `execute_call` and durable
SQLite ledger at `.chatty/github-ledger.sqlite3`. An explicit
`CHATTY_GITHUB_LEDGER_PATH` can choose another persistent file. Do not remove this
ledger during a demo or retry an uncertain write with a new call ID. A replay
with the same session, call ID and arguments returns its recorded result.
Server restarts require a new Live session; an old session ID is not accepted
and approvals are discarded. Never register or replay an old call in a new session.

This is a single-user localhost demo. Host, Origin, schema, session and call-ID
checks protect its browser boundary; another program running as the same OS
user remains trusted. The server trusts our browser's relay of Live events and
audio activity; it does not authenticate individual speakers. Confirmation uses
audio-quiet and settled-transcript heuristics because Live has no authoritative
transcript-turn-done event. Do not expose the demo through a public tunnel.
Capturing, speaking and approving a change through real meeting audio need a live
end-to-end rehearsal.
