<h1 align="center">
  <img src="landing/dist/assets/chatty-mark.svg" width="48" height="48" align="middle" alt="Chatty logo">&nbsp; Meet Chatty.
</h1>

<p align="center">
  <strong>Less searching. More conversation.</strong><br>
  Your project. In the conversation.
</p>

<p align="center">
  Built at an <a href="https://aitinkerers.org/">AI Tinkerers</a> event.
</p>

[![Meet Chatty — Your AI meeting companion. Keep the conversation moving.](landing/dist/assets/chatty-poster.jpg)](landing/dist/assets/chatty-intro.mp4)

<p align="center">
  <a href="landing/dist/assets/chatty-intro.mp4">Watch the 10-second intro</a> ·
  <a href="#the-idea">The idea</a> ·
  <a href="#try-it-locally">Try it locally</a> ·
  <a href="#whats-next">What’s next</a>
</p>

## The idea

**Your team is talking. The answers are somewhere else.**

A meeting pauses. Someone asks what changed, which pull requests are open, or what needs to happen next. The context is in GitHub; the conversation is happening somewhere else.

Chatty is an AI meeting companion in development, built to bring that project context into the conversation. Ask a question, follow the source, and turn a decision into a next step—without losing the thread.

Created at an **[AI Tinkerers](https://aitinkerers.org/) event**, Chatty explores a simple idea: the tools your team uses should support the conversation while it is happening.

## From a question to a next step

| In the conversation | What Chatty is being built to bring back |
| --- | --- |
| “What changed?” | Recent commits, with authors, timestamps, and links to the source. |
| “Which pull requests are open?” | Open PRs you can inspect in GitHub. |
| “What issues are still open?” | A list of open issues and their original records. |
| “Create an issue for this.” | An issue created from an explicit request, with a link to the result. |

These are examples of the intended conversation flow. The underlying GitHub tools are implemented; the complete meeting experience is still being connected.

### Catch up. Stay in the flow.

Bring commits, pull requests, and issues into the same context as your team’s questions.

### Find the answer. Follow the source.

Read the original record when you need the detail. GitHub results include source links, authors, and timestamps.

### A next step. At your request.

Keep the decision to act with the people in the conversation. The tool dispatcher requires explicit authorisation for issue creation, and the durable call ledger prevents blind duplicate writes when calls are redelivered.

## See the direction

The [landing page](landing/README.md) brings the concept to life with the original Chatty mark, warm paper, charcoal, and orange. Its intro plays as a silent looping background, with layouts for desktop and phone screens.

- **[Intro film](landing/dist/assets/chatty-intro.mp4)** — ten seconds from “Your team is talking” to “Meet Chatty.”
- **[Video source and production notes](https://github.com/vaishnavJa/Chatty/pull/16)** — the Remotion intro and meeting-recording edit.
- **[Hosted landing page](https://chatty-meeting-companion.takuma2460-0131.chatgpt.site)** — currently an owner-only preview; use the local preview below if you do not have access.

The intro illustrates the intended experience; it is not a recording of a working end-to-end meeting integration.

To render the intro or append a meeting recording, follow the [demo-video guide](demo-video/README.md). After installing its dependencies, run `npm run render:intro` from `demo-video/`, or `npm run render:demo -- "/path/to/meeting.mp4"` to include a recording.

## What works today

| Area | Status in this checkout |
| --- | --- |
| GitHub reads | Recent commits, open pull requests, and open issues, with source links. |
| GitHub issue creation | Explicit-request gate, validated inputs, and durable call deduplication. |
| Repository scope | GitHub tools currently target `vaishnavJa/Chatty`. |
| Landing page | Static site with the intro video, responsive layout, and reduced-motion support. |
| Conversation service | Scaffold; the backend, session authentication, and meeting UI are not wired end to end here. |
| Other connections | Slack, Google Drive, Google Chat, Jira, Teams, Confluence, and internet search are placeholders in this checkout. |

See the [GitHub integration guide](src/chatty/integrations/github/README.md) for tool schemas, authorisation requirements, error handling, and backend/UI integration details.

## Try it locally

### Python package

Requires **Python 3.12+** and **uv**.

```sh
uv sync --locked
uv run chatty
```

The command runs a scaffold readiness check and exits. It does not launch a meeting assistant or web server.

Live GitHub tool calls additionally require the `gh` CLI and an authenticated GitHub session. The integration guide describes how to connect the tools; the offline tests below do not need GitHub credentials.

### Landing page

From the repository root:

```sh
uv run --no-project python -m http.server 4173 --directory landing/dist --bind 127.0.0.1
```

Open **[localhost:4173](http://localhost:4173)** to explore the page. No API keys or frontend build step are needed.

## Build with us

```text
landing/                    Landing page, video, and brand assets
src/chatty/
├── __main__.py             Package readiness check
├── agents/                 GitHub tool schemas and dispatch
├── conversations/          Conversation scaffolding
└── integrations/
    ├── github/             Reads, issue creation, transport, and call ledger
    └── …                   Planned service integrations
tests/                      Offline GitHub tool tests
```

Run the existing development checks:

```sh
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -p 'test_github*.py'
```

The GitHub tests use fixtures and temporary storage, without making live API calls or creating real issues. Use `uv run ruff format .` to apply Python formatting.

## What’s next

- Connect the meeting audio, conversation UI, and backend into one working experience.
- Add user authentication, session ownership, and secure connection credential storage.
- Bring the GitHub tools into live conversations with source-linked answers.
- Expand beyond GitHub to the services where teams keep their context.
- Record a real meeting flow: question → source → explicitly requested action.

Have an idea or a useful meeting scenario? [Open an issue](https://github.com/vaishnavJa/Chatty/issues) and help shape what comes next.

---

<p align="center"><strong>Keep the conversation moving.</strong></p>
