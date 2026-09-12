"""HTTP boundaries shared by read-only service integrations."""

from urllib.parse import urlsplit

import httpx


class IntegrationError(Exception):
    """A configuration or remote-service failure safe to display to users."""


def require_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise IntegrationError(f"{name} must not be empty.")
    return value


def validate_limit(limit: int, maximum: int = 1000) -> None:
    if not 1 <= limit <= maximum:
        raise IntegrationError(f"Limit must be between 1 and {maximum}.")


def validate_https(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise IntegrationError(
            "Service URL must use HTTPS without embedded credentials."
        )
    if parsed.query or parsed.fragment:
        raise IntegrationError("Service URL must not contain a query or fragment.")
    return url.rstrip("/")


class JsonClient:
    """Keep credentials on one origin and avoid exposing response bodies in errors."""

    def __init__(self, base_url: str, *, headers=None, auth=None, http=None):
        self.base_url = validate_https(base_url)
        self.headers = {"Accept": "application/json", **(headers or {})}
        self.auth = auth
        self.http = http or httpx.Client(timeout=30, follow_redirects=False)
        self._owns_http = http is None

    def close(self):
        if self._owns_http:
            self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request_url(self, path: str) -> str:
        url = self.base_url + "/" + path.lstrip("/")
        if path.startswith("https://"):
            url = path
        expected = urlsplit(self.base_url)
        actual = urlsplit(url)
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise IntegrationError(
                "Refused a pagination URL outside the service origin."
            )
        return url

    def get(self, path: str, *, params=None) -> dict:
        url = self._request_url(path)
        try:
            response = self.http.get(
                url,
                headers=self.headers,
                auth=self.auth,
                params=params,
                timeout=30,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise IntegrationError(
                "Service request failed; check connectivity and retry."
            ) from None
        check_status(response)
        return decode_response(response)


def check_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise IntegrationError("Service rate limit reached; wait before retrying.")
    if response.status_code in (401, 403):
        raise IntegrationError(
            "Service authentication failed; check credentials and permissions."
        )
    if not response.is_success:
        raise IntegrationError(f"Service request failed (HTTP {response.status_code}).")


def decode_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise IntegrationError("Service returned invalid JSON.") from None
    if not isinstance(payload, dict):
        raise IntegrationError("Service returned an unexpected response format.")
    return payload


def records(payload: dict, key: str) -> list[dict]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise IntegrationError("Service returned an unexpected result collection.")
    return value
