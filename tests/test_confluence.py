import httpx
import pytest

from agent_hub.integrations.common import IntegrationError
from agent_hub.integrations.confluence import ConfluenceClient


def test_search_follows_context_relative_pagination():
    def respond(request):
        assert request.url.path == "/wiki/rest/api/search"
        if "cursor" in request.url.params:
            return httpx.Response(
                200, json={"results": [{"title": "Second", "url": "/wiki/pages/2"}]}
            )
        return httpx.Response(
            200,
            json={
                "results": [{"title": "First", "url": "/pages/1"}],
                "_links": {"next": "/rest/api/search?cursor=next"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = ConfluenceClient(
            "https://example.atlassian.net", "user@example.com", "test-token", http=http
        ).search("release", limit=2)
    assert [item["title"] for item in result] == ["First", "Second"]


def test_search_escapes_cql_literals():
    def respond(request):
        assert request.url.params["cql"] == 'type = page AND text ~ "a\\"b\\\\c"'
        return httpx.Response(200, json={"results": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert (
            ConfluenceClient(
                "https://example.atlassian.net",
                "user@example.com",
                "test-token",
                http=http,
            ).search('a"b\\c')
            == []
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:password@example.com",
        "https://example.com?token=value",
    ],
)
def test_unsafe_service_urls_are_rejected(url):
    with pytest.raises(IntegrationError):
        ConfluenceClient(url, "user@example.com", "test-token")


def test_search_returns_titles_and_absolute_source_links():
    def respond(request):
        assert request.url.path == "/wiki/rest/api/search"
        assert request.url.params["cql"] == 'type = page AND text ~ "release"'
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Release plan",
                        "url": "/spaces/ENG/pages/123",
                        "excerpt": "Next release",
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = ConfluenceClient(
            "https://example.atlassian.net", "user@example.com", "test-token", http=http
        ).search("release")
    assert result == [
        {
            "title": "Release plan",
            "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            "excerpt": "Next release",
        }
    ]


def test_reads_page_body():
    def respond(request):
        assert request.url.path == "/wiki/api/v2/pages/123"
        assert request.url.params["body-format"] == "storage"
        return httpx.Response(
            200,
            json={
                "id": "123",
                "title": "Plan",
                "body": {"storage": {"value": "<p>Ship it</p>"}},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = ConfluenceClient(
            "https://example.atlassian.net/wiki",
            "user@example.com",
            "test-token",
            http=http,
        ).page("123")
    assert result["body"]["storage"]["value"] == "<p>Ship it</p>"
