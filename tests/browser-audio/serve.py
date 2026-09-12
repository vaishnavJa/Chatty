"""Serve only the three public audio-check assets on loopback."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY = Path(__file__).resolve().parents[2]
ASSETS = {
    "/tests/browser-audio/smoke.html": (
        REPOSITORY / "tests/browser-audio/smoke.html",
        "text/html; charset=utf-8",
    ),
    "/tests/browser-audio/smoke.js": (
        REPOSITORY / "tests/browser-audio/smoke.js",
        "text/javascript; charset=utf-8",
    ),
    "/web/media.js": (
        REPOSITORY / "web/media.js",
        "text/javascript; charset=utf-8",
    ),
}


class SmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._respond(include_body=True)

    def do_HEAD(self):
        self._respond(include_body=False)

    def _respond(self, *, include_body):
        # Match the URL literally. Never decode or join a user-provided path.
        path = urlsplit(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/tests/browser-audio/smoke.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        asset = ASSETS.get(path)
        if asset is None:
            self.send_error(404, "Asset not available")
            return
        file_path, content_type = asset
        try:
            body = file_path.read_bytes()
        except OSError:
            self.send_error(404, "Asset not available")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, format, *args):
        # Keep arbitrary request URLs out of local logs.
        return


def create_server(port=8765):
    return ThreadingHTTPServer(("127.0.0.1", port), SmokeHandler)


if __name__ == "__main__":
    with create_server() as server:
        print(
            "Audio check: http://127.0.0.1:8765/tests/browser-audio/smoke.html",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
