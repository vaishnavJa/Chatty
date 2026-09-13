# Offline cross-component rehearsal

Run from the repository root with the project Python environment and Node.js:

```sh
PYTHONPATH=src python -m pytest -q tests/rehearsal/test_cross_component.py
```

This starts the **actual Chatty server on an ephemeral localhost port**, then
drives the **actual JavaScript controller and meeting-context relay** from Node.
The real voice-approval state machine, schema validation, repository adapter,
HTTP endpoints and durable write ledger run together. Runtime ports 8844/8845,
browser tabs, microphone devices, repository credentials and `.env` are untouched.

All Live transcripts, acoustic-activity notifications, function calls, and
Responses classifier replies are **explicit fixtures**. GitHub transport is
mocked. These tests establish cross-component contracts, not OpenAI reasoning,
speech recognition, actual speaker identity, virtual audio routing, or live
meeting reliability. No audio is synthesized or recorded.

The three scenarios cover:

1. Quiet participant statements and a later correction remain distinct,
   timestamped source fragments. A repository read supplies its source URL.
   Asking who is assigned answers from the saved proposal. A title amendment
   cancels the old draft and needs a fresh approval. Natural consent reaches the
   HTTP classifier fixture and executes the amended write once. Duplicate
   delivery, old evidence, cross-session reads, follow-ups and quiet listening
   are checked together.
2. A GitHub permission failure returns an error with recovery guidance, retains
   the exact draft, and never produces a success link or duplicate request.
3. A completed server receipt is deliberately held before the controller sees
   it. Stop acknowledges once and keeps input enabled. The late receipt remains
   visible while output stays muted and no response continuation restarts.

The assignee scenario uses `update_issue`: the production `create_issue` tool
currently accepts only title and body. The two remaining scenarios exercise
`create_issue`. No fixture silently grants unsupported tool arguments.

`controller_rehearsal.mjs` is launched by the Python test with its isolated server
URL. It is not a standalone `node --test` suite.
