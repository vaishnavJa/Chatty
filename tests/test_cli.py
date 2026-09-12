import json

import httpx
import pytest

from chatty.__main__ import run


@pytest.mark.parametrize(
    "arguments, path, payload",
    [
        (
            ["teams", "messages", "team", "channel"],
            "/v1.0/teams/team/channels/channel/messages",
            {"value": [{"id": "1"}]},
        ),
        (["confluence", "page", "123"], "/wiki/api/v2/pages/123", {"id": "123"}),
        (
            ["confluence", "search", "type = page", "--cql"],
            "/wiki/rest/api/search",
            {"results": []},
        ),
    ],
)
def test_service_commands_reach_the_api(arguments, path, payload, monkeypatch, capsys):
    for name, value in {
        "TEAMS_ACCESS_TOKEN": "test-token",
        "CONFLUENCE_URL": "https://example.atlassian.net",
        "CONFLUENCE_EMAIL": "user@example.com",
        "CONFLUENCE_API_TOKEN": "test-token",
    }.items():
        monkeypatch.setenv(name, value)

    def respond(request):
        assert request.url.path == path
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert run(arguments, http=http) == 0
    json.loads(capsys.readouterr().out)


def test_search_command_outputs_json(monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    def respond(request):
        assert request.url.params["q"] == "weather"
        return httpx.Response(
            200,
            json={
                "web": {"results": [{"title": "Weather", "url": "https://example.com"}]}
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert run(["search", "weather"], http=http) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"title": "Weather", "url": "https://example.com"}
    ]


def test_missing_credentials_have_actionable_error(monkeypatch, capsys):
    monkeypatch.delenv("TEAMS_ACCESS_TOKEN", raising=False)
    assert run(["teams", "list"]) == 1
    output = capsys.readouterr()
    assert "TEAMS_ACCESS_TOKEN" in output.err
    assert not output.out


def test_env_file_does_not_override_existing_credentials(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("BRAVE_SEARCH_API_KEY=file-key\n")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "environment-key")

    def respond(request):
        assert request.headers["X-Subscription-Token"] == "environment-key"
        return httpx.Response(200, json={"web": {"results": []}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert run(["--env-file", str(env_file), "search", "weather"], http=http) == 0
    assert json.loads(capsys.readouterr().out) == []
