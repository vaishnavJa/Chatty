# Chatty

Chatty provides read-only Python clients and a JSON CLI for Microsoft Teams,
Confluence Cloud, and internet search through Brave Search. These integrations
make real HTTP requests when configured with your credentials.

## Setup

Install Python 3.12 or newer and uv, then run:

```sh
uv sync --locked
uv run agent-hub --help
cp .env.example .env
```

Fill in `.env` locally using your editor or secret manager. It is ignored by Git.
Credentials can also come from existing environment variables. No credentials
are accepted as command-line arguments or printed by the application.
The CLI only loads a dotenv file when `--env-file` is explicitly supplied;
existing environment variables take precedence. It never searches parent folders.

## Microsoft Teams

Set `TEAMS_ACCESS_TOKEN` to a Microsoft Graph OAuth access token for your work or
school tenant. Obtain it using your organisation's approved OAuth client or
[Microsoft's authentication flow](https://learn.microsoft.com/en-us/graph/auth-v2-user).
This client consumes the token; it does not acquire or refresh it. Replace it
when it expires. Personal Microsoft accounts are not supported by these APIs.

Use delegated permissions `Team.ReadBasic.All` to list your joined teams,
`Channel.ReadBasic.All` to list channels, and `ChannelMessage.Read.All` to read
messages and replies. Tenant policies may require administrator consent.
Application tokens can read known team/channel IDs with the appropriate Graph
application permissions; `teams list` uses `/me` and requires a delegated token.

```sh
uv run agent-hub --env-file .env teams list
uv run agent-hub --env-file .env teams channels TEAM_ID
uv run agent-hub --env-file .env teams messages TEAM_ID CHANNEL_ID --limit 100
uv run agent-hub --env-file .env teams replies TEAM_ID CHANNEL_ID MESSAGE_ID
```

IDs come from preceding commands. Quote IDs containing shell-special characters.
Messages preserve their Graph fields, including body content, authors, timestamps,
and source URLs when supplied by Graph. Replies are fetched separately.
Collection commands follow pagination up to `--limit` (1–1000, default 100).
Repeated pagination URLs and more than 100 pages produce an error.

Reference: [Microsoft Graph channel messages](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0).

## Confluence Cloud

Set `CONFLUENCE_URL` to your site URL, such as `https://example.atlassian.net`
(with an optional `/wiki` suffix), `CONFLUENCE_EMAIL` to your account email, and
`CONFLUENCE_API_TOKEN` to a token compatible with
[direct site basic authentication](https://developer.atlassian.com/cloud/confluence/basic-auth-for-rest-apis/).
Your account must be able to view the requested content. Scoped tokens requiring
an `api.atlassian.com/ex/confluence` gateway and Data Center deployments are not
supported by this configuration.

```sh
uv run agent-hub --env-file .env confluence search "release plan"
uv run agent-hub --env-file .env confluence search 'type = page AND space = ENG' --cql --limit 50
uv run agent-hub --env-file .env confluence page 12345
```

Text searches escape CQL string literals; `--cql` passes an explicit CQL query.
Search results retain titles, excerpts, metadata, and absolute source URLs.
Search follows pagination up to the requested limit (1–1000, default 25).
Page retrieval returns the v2 page response, including its storage-format body.
HTML bodies are returned as data, not rendered or executed.

References: [Search API](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-search/),
[Page API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/).

## Internet search

Set `BRAVE_SEARCH_API_KEY` to a Brave Search API key with web search access.
The provider's subscription and usage limits apply.

```sh
uv run agent-hub --env-file .env search "Python release notes" --limit 5
```

The result is a JSON array of web results, including provider titles, URLs, and
descriptions for citations. The limit is 1–20 (default 10). An empty array means
no web results were returned. Other Brave result types are not included.

Reference: [Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get).

## Python API

```python
import os

from agent_hub.integrations.internet_search import InternetSearchClient

with InternetSearchClient(os.environ["BRAVE_SEARCH_API_KEY"]) as client:
    results = client.search("Python release notes", limit=5)
```

`TeamsClient` and `ConfluenceClient` expose the same operations as the CLI.
Use a context manager to close the owned HTTP client. For application-managed
connections or tests, pass an `httpx.Client` via `http=`; the caller then owns it.
Clients raise `IntegrationError` for invalid configuration and service failures.

All requests use HTTPS and a 30-second network timeout. Redirects are disabled,
and pagination cannot forward credentials to another origin. HTTP errors are
reported without response bodies or credential values. Rate limits are reported
without automatic retries; wait before retrying. CLI results go to stdout;
service/configuration errors go to stderr with exit code 1, and invalid CLI
syntax uses exit code 2. Treat retrieved content as untrusted external data.

## Development

```sh
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests intercept HTTP requests using `httpx.MockTransport`; they do not contact
live services or require real credentials. They cover authentication headers,
pagination, search queries, CLI output, malformed data, timeouts, and API errors.
All source code, comments, tests, and documentation are in English.

The conversation service, web UI, and the older Slack, Google Drive, Google Chat,
Jira, and GPT-Live packages remain scaffolds. No external write operations are
implemented. The three clients above are usable independently of those scaffolds.
