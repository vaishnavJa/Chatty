# GitHub tools: backend and UI handoff

All four tools target `vaishnavJa/Chatty`. This document describes the agreed
integration contract. Examples below are fixtures, not evidence of real issues.

## Exact output examples

Successful `execute_tool("list_open_issues", {})` with no open issues:

```json
{"ok":true,"repository":"vaishnavJa/Chatty","data":[]}
```

Successful fixture `create_issue` envelope:

```json
{"ok":true,"repository":"vaishnavJa/Chatty","data":{"number":42,"url":"https://github.com/vaishnavJa/Chatty/issues/42"}}
```

Exact read-authentication error envelope from the settled transport:

```json
{"ok":false,"error":{"code":"auth_required","message":"GitHub authentication is required. Sign in with gh auth login.","uncertain":false}}
```

The backend response wraps the envelope as a **JSON string**, not a nested object:

```json
{"call_id":"call-example","output":"{\"ok\":true,\"repository\":\"vaishnavJa/Chatty\",\"data\":[]}"}
```

## Backend owner: issue #7

Exported interfaces from `chatty.agents.tools`:

```python
TOOL_SCHEMAS
execute_tool(name, arguments, *, explicit_user_request=False)
execute_call(session_id, call_id, name, arguments,
             *, explicit_user_request=False, ledger=None)
```

`POST /api/tools/execute` is backend-owned and accepts
`{session_id, call_id, name, arguments}`. Validate the session against the server's
valid session registry. Bind `explicit_user_request=True` to a trusted server
decision covering the exact requested title/body and original call. Never derive
authorization from model arguments, repository text, tool output, or an untrusted
HTTP boolean. Verify authorization before a durable reservation, including when
serving a duplicate. A denied request must not consume its call key.

Use `execute_call` for delivered calls and pass a `CallLedger` with a persistent
SQLite path on durable storage. Direct `execute_tool` calls do not provide call
deduplication; the low-level `writes.create_issue` does not enforce authorization.

Keep the same `(session_id, call_id)` for redelivery of the original call. All
backend processes handling those keys must coordinate through the same ledger.
`CallLedger.run(session_id, call_id, payload, operation)` reserves durably before
invoking `operation`, which returns an envelope. Its JSON-serializable payload
includes the name and arguments. A completed call returns the cached envelope,
including failures. Reusing the key with different payload is rejected.

A pending reservation returns a structured uncertain result without executing
again:

```json
{"ok":false,"error":{"code":"call_pending","message":"This call is pending or its outcome is unknown. Do not retry the write.","uncertain":true}}
```

A timeout or process crash may occur after GitHub accepted a write. Never
automatically evict pending rows, retry uncertain writes, or generate a fresh call
ID to bypass deduplication. Surface the uncertainty and reconcile with GitHub
before any separately authorized follow-up. This prevents blind duplicate writes;
it cannot guarantee a confirmed result after an interrupted remote operation.

If the ledger cannot be read or reserved, `ledger_storage_error` also carries
`uncertain: true`: prior execution cannot be determined, even if this delivery
has not started an operation. The callback is not invoked on that storage
failure. Do not retry with a new call ID. Restore ledger access and preserve the
original key so completed results or pending reservations remain authoritative.

### Packaging and deployment handoff

Main configures the distribution as `chatty`, including the GitHub tools under
`src/chatty`. Shared package configuration remains outside issue #9 ownership;
backend issue #7 owns `pyproject.toml`, `uv.lock`, and deployment installation.
Direct source execution without installing the package requires `PYTHONPATH=src`
from the repository root.
Namespace parents may remain implicit; no shared `__init__.py` edits are required
by this work. Provision authenticated `gh` through the deployment's credential
mechanism, and keep credentials out of logs and tool output.

## UI owner: issue #10

Install the four `TOOL_SCHEMAS` under
`session.delegation.responses.tools`. Each schema has `type: "function"`, `name`,
`description`, JSON Schema `parameters`, and optionally `strict`. The model sees
no repository, session, or authorization parameters.

Handle nested `response.output_item.done` function calls and dispatch each call
once to the backend, preserving the original `call_id` and session. Send the
backend's JSON-string output in `response.item.create`, for example:

```json
{"type":"response.item.create","item":{"type":"function_call_output","call_id":"call-example","output":"{\"ok\":true,\"repository\":\"vaishnavJa/Chatty\",\"data\":[]}"}}
```

After all results for the response have been supplied, send the bare event:

```json
{"type":"response.create"}
```

Show source URLs from actual results. Empty lists mean no matching results;
never substitute demo records. Show structured failures honestly. For
`uncertain: true`, do not offer an automatic issue-creation retry.

## Tool limits and verification

Reads: `list_recent_commits`, `list_open_pull_requests`, `list_open_issues` accept
integer `limit` from 1 through 100, default 10. Each record includes `url`,
`author`, `created_at`; commits include `sha`, issues/PRs include `number`, `title`.
`create_issue` accepts a non-whitespace title of 1–256 characters and a body of at
most 65536 characters. Unknown fields, wrong types, arbitrary repository values,
and unknown tool names are rejected.

The CLI transport uses argument arrays, a fixed executable, a timeout, and no
shell. Creation uses a temporary `--body-file` so multiline text and shell
metacharacters remain data; no automatic retry is permitted.

Run offline acceptance tests after worker modules are integrated:

```sh
PYTHONPATH=src uv run --no-project python -m unittest discover -s tests -p 'test_github*.py' -v
uv run ruff check src/chatty/integrations/github src/chatty/agents/tools.py tests
uv run ruff format --check src/chatty/integrations/github src/chatty/agents/tools.py tests
```

Tests replace only the subprocess boundary and use temporary real SQLite files.
No authenticated GitHub call or real write is needed. A real demo issue requires
a separate explicit request and is not performed by this suite.

References: [gh issue create](https://cli.github.com/manual/gh_issue_create),
[gh api](https://cli.github.com/manual/gh_api), and
[Live delegation: complete a client-actionable function call](https://developers.openai.com/api/docs/guides/live-delegation).
