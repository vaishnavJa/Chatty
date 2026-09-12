"""Local HTTP boundary shared by the browser, Live, and GitHub tool owners."""

import json
import mimetypes
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from chatty.config import Settings
from chatty.integrations.gpt_live.client import LiveClient, LiveError
from chatty.integrations.gpt_live.executor import (
    ExecutorError,
    ToolExecutor,
    ToolRegistry,
)

MAX_IDENTIFIER_LENGTH = 256
STATIC_EXTENSIONS = {
    ".html",
    ".js",
    ".css",
    ".json",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
}


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON number")


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def parse_json(data: bytes) -> dict:
    try:
        value = json.loads(
            data,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicates,
        )
        if not isinstance(value, dict):
            raise ValueError
        # Exponent overflow (e.g. 1e9999) is not routed through parse_constant.
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ExecutorError(
            400, "invalid_json", "Expected a valid JSON object."
        ) from None


def required_string(body: dict, key: str, maximum: int) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ExecutorError(
            400,
            "invalid_request",
            f"A nonempty {key} string is required (maximum {maximum} characters).",
        )
    return value


class ChattyApp:
    def __init__(self, settings: Settings, *, live_client=None, tool_factory=None):
        self.settings = settings
        self.live = live_client if live_client is not None else LiveClient(settings)
        self.tool_factory = tool_factory or ToolRegistry.from_module
        self.executor = ToolExecutor(settings)
        # Serializes capacity check + upstream creation + registration.
        self.creation_lock = threading.Lock()

    def create_session(self, body: dict) -> dict:
        if set(body) != {"sdp"}:
            raise ExecutorError(400, "invalid_request", "Expected only the sdp field.")
        sdp = required_string(body, "sdp", 60_000)
        try:
            tools = self.tool_factory()
        except Exception:
            raise ExecutorError(
                503,
                "invalid_tool_module",
                "The GitHub tool module could not be loaded. Check its exports and dependencies.",
            ) from None
        with self.creation_lock:
            self.executor.ensure_capacity()
            result = self.live.create_session(sdp, tools.schemas)
            self.executor.register(result["session"]["id"], tools)
        return result

    def execute_tool(self, body: dict) -> dict:
        if set(body) != {"session_id", "call_id", "name", "arguments"}:
            raise ExecutorError(
                400,
                "invalid_request",
                "Expected session_id, call_id, name, and arguments.",
            )
        session_id = required_string(body, "session_id", MAX_IDENTIFIER_LENGTH)
        call_id = required_string(body, "call_id", MAX_IDENTIFIER_LENGTH)
        name = required_string(body, "name", 64)
        arguments = body["arguments"]
        if not isinstance(arguments, dict):
            raise ExecutorError(
                400,
                "invalid_arguments",
                "arguments must be a parsed JSON object, not a JSON string.",
            )
        return self.executor.execute(session_id, call_id, name, arguments)

    def health(self) -> dict:
        try:
            tools = self.tool_factory()
            tool_status = "ready" if tools.available else "not_installed"
        except Exception:
            tool_status = "invalid"
        return {
            "status": "ok",
            "openai_configured": bool(self.settings.api_key),
            "tools": tool_status,
            "web_ready": (self.settings.web_dir / "index.html").is_file(),
        }


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app: ChattyApp):
        self.app = app
        # Binding is intentionally not configurable: no public unauthenticated
        # GitHub-write server, even if CHATTY_HOST is accidentally set to 0.0.0.0.
        super().__init__(("127.0.0.1", app.settings.port), Handler)
        port = self.server_address[1]
        self.allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}

    def server_close(self) -> None:
        super().server_close()
        self.app.live.close()


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "Chatty"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)
        self.body_bytes_read = 0

    def finish(self) -> None:
        # Closing a Windows socket with unread POST data can reset the connection
        # before the browser receives our error. Send the response, half-close,
        # then discard a bounded amount of rejected input before closing fully.
        try:
            self.wfile.flush()
            lengths = getattr(self, "headers", {}).get("Content-Length", "")
            if getattr(self, "command", None) == "POST" and lengths.isdigit():
                remaining = min(
                    int(lengths) - self.body_bytes_read,
                    self.server.app.settings.max_body_bytes * 2,
                )
                if remaining > 0:
                    self.connection.shutdown(socket.SHUT_WR)
                    deadline = time.monotonic() + 0.25
                    while remaining > 0:
                        timeout = deadline - time.monotonic()
                        if timeout <= 0:
                            break
                        self.connection.settimeout(timeout)
                        chunk = self.rfile.read1(min(remaining, 8192))
                        if not chunk:
                            break
                        remaining -= len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            super().finish()

    def log_message(self, format, *args) -> None:
        # Do not log bodies, SDP, arbitrary URLs, or upstream exceptions.
        pass

    def reply(self, status: int, body: bytes, content_type="application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # Tool execution/receipt recording has already completed. A lost
                # browser response must not cause the tool to run a second time.
                pass

    def json_reply(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False, allow_nan=False)
        self.reply(status, self.server.app.settings.redact(data).encode("utf-8"))

    def failure(self, error: ExecutorError | LiveError) -> None:
        self.json_reply(error.status, {"error": str(error), "code": error.code})

    def check_host(self) -> None:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in self.server.allowed_hosts:
            raise ExecutorError(403, "invalid_host", "Use this app's localhost URL.")

    def read_body(self) -> dict:
        self.check_host()
        origins = self.headers.get_all("Origin", [])
        if origins != [f"http://{self.headers['Host']}"]:
            raise ExecutorError(
                403,
                "invalid_origin",
                "Requests must originate from the local Chatty page.",
            )
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ExecutorError(
                403, "invalid_origin", "Cross-site requests are not allowed."
            )
        if self.headers.get_content_type() != "application/json":
            raise ExecutorError(415, "invalid_content_type", "Use application/json.")
        lengths = self.headers.get_all("Content-Length", [])
        if (
            len(lengths) != 1
            or not lengths[0].isdigit()
            or self.headers.get("Transfer-Encoding")
        ):
            raise ExecutorError(
                400, "invalid_length", "A valid Content-Length is required."
            )
        length = int(lengths[0])
        if not 0 < length <= self.server.app.settings.max_body_bytes:
            raise ExecutorError(
                413,
                "request_too_large",
                "Request body must be between 1 and 65536 bytes.",
            )
        data = self.rfile.read(length)
        self.body_bytes_read = len(data)
        if len(data) != length:
            raise ExecutorError(
                400, "incomplete_body", "The request body was incomplete."
            )
        return parse_json(data)

    def do_POST(self) -> None:
        try:
            if self.path not in {"/api/live/session", "/api/tools/execute"}:
                raise ExecutorError(404, "not_found", "Unknown endpoint.")
            body = self.read_body()
            if self.path == "/api/live/session":
                self.json_reply(201, self.server.app.create_session(body))
            else:
                self.json_reply(200, self.server.app.execute_tool(body))
        except (ExecutorError, LiveError) as error:
            self.failure(error)
        except TimeoutError:
            self.failure(
                ExecutorError(408, "request_timeout", "Reading the request timed out.")
            )
        except Exception:
            self.failure(
                ExecutorError(
                    500, "internal_error", "The server could not complete the request."
                )
            )

    def do_GET(self) -> None:
        try:
            self.check_host()
            path = unquote(urlsplit(self.path).path)
            if path == "/api/health":
                self.json_reply(200, self.server.app.health())
                return
            root = self.server.app.settings.web_dir.resolve()
            if path == "/" and not (root / "index.html").is_file():
                self.reply(
                    200,
                    b"<!doctype html><html lang='en'><meta charset='utf-8'><title>Chatty backend</title><h1>Chatty backend is running</h1><p>The demo UI has not been integrated yet. Add the UI owner's web/ files and refresh.</p></html>",
                    "text/html; charset=utf-8",
                )
                return
            relative = path.lstrip("/") or "index.html"
            if "\\" in relative or any(
                part.startswith(".") for part in relative.split("/")
            ):
                raise ExecutorError(404, "not_found", "File not found.")
            target = (root / relative).resolve()
            if (
                not target.is_relative_to(root)
                or not target.is_file()
                or target.suffix.lower() not in STATIC_EXTENSIONS
            ):
                raise ExecutorError(404, "not_found", "File not found.")
            content_type = (
                "text/javascript"
                if target.suffix == ".js"
                else mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )
            self.reply(200, target.read_bytes(), content_type)
        except (ValueError, OSError):
            self.failure(ExecutorError(404, "not_found", "File not found."))
        except ExecutorError as error:
            self.failure(error)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_OPTIONS(self) -> None:
        self.failure(
            ExecutorError(
                403, "cross_origin_disabled", "Cross-origin API access is disabled."
            )
        )


def create_server(settings: Settings | None = None, **app_kwargs) -> LocalServer:
    """Factory supports injected Live clients and tool fixtures for offline tests."""
    return LocalServer(ChattyApp(settings or Settings.from_env(), **app_kwargs))
