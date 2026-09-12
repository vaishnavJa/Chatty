# Agent Hub

An empty scaffold for a conversational agent service that uses information from external services.
The working project name is `agent-hub`.

## Getting started

```sh
uv sync --locked
uv run agent-hub
```

The project uses Python 3.12 or later, uv, and Ruff. The entry point prints a readiness message and exits.
There is no web server or user interface yet.

## Development checks

```sh
uv run ruff check .
uv run ruff format --check .
```

Run `uv run ruff format .` to apply formatting.

## Project structure

```text
src/agent_hub/
├── __main__.py          # Smoke-check entry point
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

Each package is currently a placeholder.
Authentication, API calls, conversation persistence, and agent execution are not implemented.
The specific GPT-Live service and API will be selected during implementation.

The Teams, Confluence, and Internet Search packages are also placeholders.
Service connections and internet searches cannot be performed yet.
The Internet Search provider and API will be selected during implementation.
The agent is intended to access search result titles, URLs, and summaries.

Environment variable loading is not implemented yet. `.env` is excluded from Git.

## Next implementation steps

1. Choose the conversation UI and backend API architecture.
2. Define the GPT-Live integration and implement the first agent conversation.
3. Implement user authentication and connection credential storage.
4. Integrate Slack, Google Drive, Google Chat, Jira, Teams, and Confluence.
5. Select an Internet Search API and include source URLs in conversation responses.
6. Require user confirmation before sending data to or updating external services.
