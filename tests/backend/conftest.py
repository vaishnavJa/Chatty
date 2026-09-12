import threading
from dataclasses import replace

import httpx
import pytest

from chatty.config import Settings
from chatty.integrations.gpt_live.executor import ToolRegistry
from chatty.server import create_server

SCHEMAS = [
    {
        "type": "function",
        "name": "create_issue",
        "description": "Create an explicitly requested issue.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1}},
            "required": ["title"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


@pytest.fixture
def settings(tmp_path):
    return Settings(api_key="test-openai-secret", port=0, web_dir=tmp_path / "web")


@pytest.fixture
def schemas():
    return SCHEMAS


class FakeLive:
    def __init__(self):
        self.requests = []

    def create_session(self, sdp, schemas):
        self.requests.append((sdp, schemas))
        return {
            "session": {"id": f"opaque-session-{len(self.requests)}"},
            "transport": {"type": "webrtc", "sdp": "v=0\r\nanswer\r\n"},
        }

    def close(self):
        pass


@pytest.fixture
def server_fixture(settings):
    servers = []

    def start(*, runner=None, tools=None, live=None, **overrides):
        calls = []

        def execute(name, arguments):
            calls.append((name, arguments))
            if runner is not None:
                return runner(name, arguments)
            return {
                "number": 42,
                "url": "https://github.com/vaishnavJa/Chatty/issues/42",
            }

        registry = tools if tools is not None else ToolRegistry(SCHEMAS, execute)
        gateway = live if live is not None else FakeLive()
        server = create_server(
            replace(settings, **overrides),
            live_client=gateway,
            tool_factory=lambda: registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        client = httpx.Client(
            base_url=base, headers={"Origin": base}, trust_env=False, timeout=5
        )
        servers.append((server, thread, client))
        return server, client, gateway, calls

    yield start
    for server, thread, client in servers:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
