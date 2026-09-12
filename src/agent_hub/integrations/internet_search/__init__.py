"""Internet search with Brave Search API."""

from agent_hub.integrations.common import (
    IntegrationError,
    JsonClient,
    records,
    require_text,
    validate_limit,
)


class InternetSearchClient(JsonClient):
    def __init__(self, api_key: str, *, http=None):
        super().__init__(
            "https://api.search.brave.com/res/v1",
            http=http,
            headers={"X-Subscription-Token": require_text(api_key, "Brave API key")},
        )

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        validate_limit(limit, 20)
        payload = self.get(
            "web/search", params={"q": require_text(query, "Query"), "count": limit}
        )
        web = payload.get("web", {"results": []})
        if not isinstance(web, dict):
            raise IntegrationError("Service returned an unexpected search response.")
        return records(web, "results")[:limit]
