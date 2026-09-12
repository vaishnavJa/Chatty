"""Search Confluence Cloud and retrieve page bodies."""

from urllib.parse import urljoin

import httpx

from chatty.integrations.common import (
    IntegrationError,
    JsonClient,
    records,
    require_text,
    validate_https,
    validate_limit,
)


class ConfluenceClient(JsonClient):
    def __init__(self, site_url: str, email: str, api_token: str, *, http=None):
        base = validate_https(site_url)
        if not base.endswith("/wiki"):
            base += "/wiki"
        super().__init__(
            base,
            http=http,
            auth=httpx.BasicAuth(
                require_text(email, "Confluence email"),
                require_text(api_token, "Confluence API token"),
            ),
        )

    def search(self, query: str, *, limit: int = 25) -> list[dict]:
        require_text(query, "Query")
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        return self.search_cql(f'type = page AND text ~ "{escaped}"', limit=limit)

    def search_cql(self, cql: str, *, limit: int = 25) -> list[dict]:
        validate_limit(limit)
        params = {"cql": require_text(cql, "CQL"), "limit": min(limit, 100)}
        path = "rest/api/search"
        results = []
        seen = set()
        while path:
            if path in seen or len(seen) >= 100:
                raise IntegrationError(
                    "Service returned invalid or excessive pagination."
                )
            seen.add(path)
            payload = self.get(path, params=params)
            for item in records(payload, "results"):
                result = dict(item)
                result["url"] = self._source_url(item.get("url", ""))
                results.append(result)
            if len(results) >= limit:
                return results[:limit]
            path = self._next_page(payload)
            params = None
        return results

    def _next_page(self, payload: dict) -> str:
        links = payload.get("_links", {})
        if not isinstance(links, dict) or not isinstance(links.get("next", ""), str):
            raise IntegrationError("Service returned invalid pagination.")
        next_path = links.get("next", "")
        return self._source_url(next_path) if next_path else ""

    def _source_url(self, path: str) -> str:
        if not isinstance(path, str):
            raise IntegrationError("Service returned an invalid source URL.")
        if path.startswith(("https://", "/wiki/")):
            return urljoin(self.base_url, path)
        return self.base_url + "/" + path.lstrip("/")

    def page(self, page_id: str) -> dict:
        if not page_id.isascii() or not page_id.isdecimal():
            raise IntegrationError("Confluence page ID must contain ASCII digits only.")
        return self.get(f"api/v2/pages/{page_id}", params={"body-format": "storage"})
