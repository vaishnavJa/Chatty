import httpx
import pytest

from agent_hub.integrations.common import IntegrationError
from agent_hub.integrations.teams import TeamsClient


@pytest.mark.parametrize(
    "operation, arguments, path",
    [
        ("teams", (), "/v1.0/me/joinedTeams"),
        ("channels", ("team",), "/v1.0/teams/team/channels"),
        (
            "replies",
            ("team", "channel", "message"),
            "/v1.0/teams/team/channels/channel/messages/message/replies",
        ),
    ],
)
def test_discovery_and_reply_endpoints(operation, arguments, path):
    def respond(request):
        assert request.url.path == path
        return httpx.Response(200, json={"value": [{"id": "123"}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = TeamsClient("test-token", http=http)
        assert getattr(client, operation)(*arguments) == [{"id": "123"}]


def test_result_limit_does_not_fetch_another_page():
    def respond(request):
        assert "cursor" not in request.url.params
        return httpx.Response(
            200,
            json={
                "value": [{"id": "1"}, {"id": "2"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/joinedTeams?cursor=next",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert TeamsClient("test-token", http=http).teams(limit=1) == [{"id": "1"}]


def test_repeated_pagination_is_rejected():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/joinedTeams",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(IntegrationError, match="pagination"):
            TeamsClient("test-token", http=http).teams()


def test_reads_channel_messages_across_pages():
    def respond(request):
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/v1.0/teams/team/channels/channel/messages"
        if "cursor" in request.url.params:
            return httpx.Response(
                200, json={"value": [{"id": "2", "body": {"content": "Second"}}]}
            )
        return httpx.Response(
            200,
            json={
                "value": [{"id": "1", "body": {"content": "First"}}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/teams/team/channels/channel/messages?cursor=next",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = TeamsClient("test-token", http=http).messages(
            "team", "channel", limit=2
        )
    assert [message["body"]["content"] for message in result] == ["First", "Second"]


def test_refuses_to_forward_credentials_to_pagination_host():
    def respond(request):
        assert request.url.host == "graph.microsoft.com"
        return httpx.Response(
            200,
            json={"value": [], "@odata.nextLink": "https://untrusted.example/messages"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(IntegrationError, match="outside the service origin"):
            TeamsClient("test-token", http=http).messages("team", "channel")
