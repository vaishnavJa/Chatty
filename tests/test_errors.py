import httpx
import pytest

from agent_hub.integrations.common import IntegrationError
from agent_hub.integrations.internet_search import InternetSearchClient


@pytest.mark.parametrize(
    "status, message",
    [
        (401, "authentication"),
        (403, "permissions"),
        (429, "rate limit"),
        (500, "HTTP 500"),
        (302, "HTTP 302"),
    ],
)
def test_http_errors_do_not_expose_response_secrets(status, message):
    def respond(request):
        return httpx.Response(
            status,
            text="secret-value",
            headers={"Location": "https://untrusted.example"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(IntegrationError, match=message) as error:
            InternetSearchClient("secret-value", http=http).search("test")
    assert "secret-value" not in str(error.value)


@pytest.mark.parametrize(
    "payload", [[], {"web": []}, {"web": {"results": "bad"}}, {"web": {"results": [1]}}]
)
def test_malformed_results_fail_cleanly(payload):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(IntegrationError, match="unexpected"):
            InternetSearchClient("test-key", http=http).search("test")


def test_timeout_does_not_expose_request_details():
    def respond(request):
        raise httpx.ReadTimeout("secret-value", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(IntegrationError, match="connectivity") as error:
            InternetSearchClient("secret-value", http=http).search("private-query")
    assert "secret-value" not in str(error.value)


def test_invalid_json_fails_cleanly():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="not json")
        )
    ) as http:
        with pytest.raises(IntegrationError, match="invalid JSON"):
            InternetSearchClient("test-key", http=http).search("test")


@pytest.mark.parametrize(
    "query, limit", [("", 10), ("   ", 10), ("test", 0), ("test", 21)]
)
def test_invalid_search_input_is_rejected_before_network(query, limit):
    def unexpected(request):
        pytest.fail("Invalid input must not reach the network")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as http:
        with pytest.raises(IntegrationError):
            InternetSearchClient("test-key", http=http).search(query, limit=limit)
