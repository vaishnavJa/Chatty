# Chatty

A local meeting assistant using OpenAI GPT-Live and repository tools.
The Python package and command are named `chatty`.

## Getting started

```sh
uv sync --locked
# Copy .env.example to .env and set OPENAI_API_KEY locally.
uv run chatty
```

The project uses Python 3.12 or later, uv, and Ruff. Open http://localhost:3000.
The server binds only to the demo laptop and serves the UI owner's `web/` files.
Before those files land, it displays a backend-ready page. Live sessions require
an API key with GPT-Live access and an available `OPENAI_BACKEND_MODEL`.

See [the backend handoff](docs/backend-handoff.md) for the exact session/tool
contracts, teammate integration instructions, local trust model, and audio test checklist.

## Development checks

```sh
uv run pytest tests/backend
uv run ruff check .
uv run ruff format --check .
```

Run `uv run ruff format .` to apply formatting.

## Project structure

```text
src/chatty/
├── __main__.py          # Local server entry point
├── config.py            # Server-only environment configuration
├── server.py            # Local UI, session, and tool-execution endpoints
├── conversations/      # Conversations, messages, and sessions
├── agents/             # Agent execution and tool calls
└── integrations/       # Service-specific integrations
    ├── gpt_live/
    ├── slack/
    ├── google_drive/
    ├── google_chat/
    ├── jira/
    ├── teams/
    ├── confluence/
    └── internet_search/
```

The GPT-Live integration creates voice sessions with managed Responses delegation.
The GitHub owner supplies `chatty.agents.tools.TOOL_SCHEMAS` and `execute_tool`.
The backend registers sessions, validates tool calls, and deduplicates execution.
Other service packages remain placeholders.

The Teams, Confluence, and Internet Search packages are also placeholders.
Service connections and internet searches cannot be performed yet.
The Internet Search provider and API will be selected during implementation.
The agent is intended to access search result titles, URLs, and summaries.

Environment variables load from the repository's `.env`, which is excluded from Git.
Existing environment variables take precedence. Never place credentials in `web/`.

## Next implementation steps

The four demo issues split ownership across the Live backend, meeting audio,
GitHub tools, and UI. Integrate their documented interfaces, then verify a real
meeting conversation and one explicitly requested issue creation. Jira and other
services are future work. This demo is for a trusted operator on one laptop;
multi-user authentication and approval workflows are not implemented.
