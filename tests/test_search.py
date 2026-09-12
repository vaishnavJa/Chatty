import httpx

from agent_hub.integrations.internet_search import InternetSearchClient


def test_search_returns_citable_results():
    def respond(request):
        assert request.url.host == "api.search.brave.com"
        assert request.url.params["q"] == "release notes"
        assert request.headers["X-Subscription-Token"] == "test-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Release",
                            "url": "https://example.com/release",
                            "description": "New version",
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        results = InternetSearchClient("test-key", http=http).search("release notes")
    assert results == [
        {
            "title": "Release",
            "url": "https://example.com/release",
            "description": "New version",
        }
    ]
