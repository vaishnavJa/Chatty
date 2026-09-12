"""Exercise the public-asset allowlist without opening any private file."""

import importlib.util
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "chatty_audio_smoke_server", Path(__file__).with_name("serve.py")
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class SmokeServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = smoke.create_server(port=0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, method="GET"):
        connection = HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_binds_only_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_allowed_assets_have_correct_content_type(self):
        expected = {
            "/tests/browser-audio/smoke.html": (
                "text/html; charset=utf-8",
                b"Chatty audio route check",
            ),
            "/tests/browser-audio/smoke.js": (
                "text/javascript; charset=utf-8",
                b'from "../../web/media.js"',
            ),
            "/web/media.js": (
                "text/javascript; charset=utf-8",
                b"export async function captureInput",
            ),
        }
        for path, (content_type, marker) in expected.items():
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], content_type)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertIn(marker, body)

    def test_root_redirect_keeps_relative_module_imports_working(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/tests/browser-audio/smoke.html")
        self.assertEqual(body, b"")

    def test_head_returns_asset_headers_without_body(self):
        status, headers, body = self.request("/web/media.js", "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(body, b"")

    def test_denied_paths_never_read_a_file(self):
        denied = (
            "/.env",
            "/openai.env.md",
            "/.git/config",
            "/tests/browser-audio/../../.env",
            "/tests/browser-audio/%2e%2e/%2e%2e/.env",
            "/tests/browser-audio/%252e%252e/%252e%252e/.env",
            "/%2e%2e/openai.env.md",
            "/web/..%2f.env",
            "/web/media.js/../../.env",
            "/tests/browser-audio/",
            "/web/",
            "/web/live.js",
            "/tests/browser-audio/serve.py",
            "/unlisted.js",
        )
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("Denied paths must not read files"),
        ):
            for path in denied:
                with self.subTest(path=path):
                    status, _, _ = self.request(path)
                    self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
