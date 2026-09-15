"""Public test suite for the inventory dashboard service."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.app import create_app  # noqa: E402
from service.store import INVENTORY  # noqa: E402


TEST_TOKEN = "test-token-for-public-suite"


def _get(port: int, path: str, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_app(TEST_TOKEN)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)

    def test_health_is_public(self) -> None:
        status, body = _get(self.port, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})

    def test_inventory_requires_auth(self) -> None:
        status, _ = _get(self.port, f"/api/inventory/{sorted(INVENTORY)[0]}")
        self.assertEqual(status, 401)

    def test_inventory_serves_known_sku(self) -> None:
        sku = sorted(INVENTORY)[0]
        status, body = _get(self.port, f"/api/inventory/{sku}", TEST_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sku": sku, "on_hand": INVENTORY[sku]})

    def test_inventory_unknown_sku_404_with_auth(self) -> None:
        status, _ = _get(self.port, "/api/inventory/SKU-NOPE-99", TEST_TOKEN)
        self.assertEqual(status, 404)

    def test_daily_report_requires_auth(self) -> None:
        status, _ = _get(self.port, "/api/reports/daily")
        self.assertEqual(status, 401)

    def test_daily_report_callback_forbidden(self) -> None:
        status, body = _get(self.port, "/api/reports/daily?callback_url=http://evil.com/hook", TEST_TOKEN)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden callback url")

        status, body = _get(self.port, "/api/reports/daily?callback_url=http://ops.meridian-logistics.example/hook", TEST_TOKEN)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden callback url")

        status, body = _get(self.port, "/api/reports/daily?callback_url=https://127.0.0.1/hook", TEST_TOKEN)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden callback url")

    def test_daily_report_callback_success(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        import urllib.parse
        
        callback_data = []
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                data = self.rfile.read(length)
                callback_data.append(json.loads(data.decode("utf-8")))
                self.send_response(200)
                self.end_headers()
                
            def log_message(self, format: str, *args: object) -> None:
                pass
                
        cb_server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        cb_port = cb_server.server_address[1]
        cb_thread = threading.Thread(target=cb_server.serve_forever, daemon=True)
        cb_thread.start()
        
        try:
            callback_url = urllib.parse.quote(f"http://127.0.0.1:{cb_port}/hook")
            status, body = _get(self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN)
            self.assertEqual(status, 200)
            
            self.assertEqual(len(callback_data), 1)
            self.assertEqual(callback_data[0]["total_skus"], len(INVENTORY))
        finally:
            cb_server.shutdown()
            cb_server.server_close()
            cb_thread.join(timeout=10)

    def test_daily_report_callback_redirect_not_followed(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        import urllib.parse
        
        callback_data = []
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == "/redirect":
                    self.send_response(307)
                    self.send_header('Location', f'http://127.0.0.1:{self.server.server_address[1]}/target')
                    self.end_headers()
                elif self.path == "/target":
                    length = int(self.headers["Content-Length"])
                    data = self.rfile.read(length)
                    callback_data.append(json.loads(data.decode("utf-8")))
                    self.send_response(200)
                    self.end_headers()
                
            def log_message(self, format: str, *args: object) -> None:
                pass
                
        cb_server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        cb_port = cb_server.server_address[1]
        cb_thread = threading.Thread(target=cb_server.serve_forever, daemon=True)
        cb_thread.start()
        
        try:
            callback_url = urllib.parse.quote(f"http://127.0.0.1:{cb_port}/redirect")
            status, body = _get(self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN)
            self.assertEqual(status, 200)
            
            # Since redirect should NOT be followed, callback_data should be empty
            self.assertEqual(len(callback_data), 0)
        finally:
            cb_server.shutdown()
            cb_server.server_close()
            cb_thread.join(timeout=10)

    def test_daily_report_payload(self) -> None:
        status, body = _get(self.port, "/api/reports/daily", TEST_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body["date"], datetime.now(timezone.utc).date().isoformat())
        self.assertEqual(body["total_skus"], len(INVENTORY))
        self.assertEqual(
            body["low_stock"],
            [
                {"sku": sku, "on_hand": INVENTORY[sku]}
                for sku in sorted(INVENTORY)
                if INVENTORY[sku] < 20
            ],
        )


if __name__ == "__main__":
    unittest.main()
