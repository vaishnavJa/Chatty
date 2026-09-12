"""Read Microsoft Teams through Microsoft Graph v1.0."""

from urllib.parse import quote

from agent_hub.integrations.common import (
    IntegrationError,
    JsonClient,
    records,
    require_text,
    validate_limit,
)


def identifier(value: str) -> str:
    require_text(value, "Resource ID")
    if value in (".", ".."):
        raise IntegrationError("Invalid resource ID.")
    return quote(value, safe="")


class TeamsClient(JsonClient):
    def __init__(self, access_token: str, *, http=None):
        super().__init__(
            "https://graph.microsoft.com/v1.0",
            http=http,
            headers={
                "Authorization": "Bearer "
                + require_text(access_token, "Teams access token")
            },
        )

    def _collection(self, path: str, limit: int) -> list[dict]:
        validate_limit(limit)
        result = []
        seen = set()
        while path:
            if not isinstance(path, str) or path in seen or len(seen) >= 100:
                raise IntegrationError(
                    "Service returned invalid or excessive pagination."
                )
            seen.add(path)
            payload = self.get(path)
            result.extend(records(payload, "value"))
            if len(result) >= limit:
                return result[:limit]
            path = payload.get("@odata.nextLink", "")
        return result

    def teams(self, *, limit: int = 100) -> list[dict]:
        return self._collection("me/joinedTeams", limit)

    def channels(self, team_id: str, *, limit: int = 100) -> list[dict]:
        return self._collection(f"teams/{identifier(team_id)}/channels", limit)

    def messages(
        self, team_id: str, channel_id: str, *, limit: int = 100
    ) -> list[dict]:
        path = f"teams/{identifier(team_id)}/channels/{identifier(channel_id)}/messages"
        return self._collection(path, limit)

    def replies(
        self, team_id: str, channel_id: str, message_id: str, *, limit: int = 100
    ) -> list[dict]:
        path = f"teams/{identifier(team_id)}/channels/{identifier(channel_id)}/messages/{identifier(message_id)}/replies"
        return self._collection(path, limit)
