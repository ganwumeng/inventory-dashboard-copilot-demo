"""Public test suite for the inventory dashboard service."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import unittest.mock
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

    def test_daily_report_callback_url_invalid(self) -> None:
        invalid_urls = [
            "http://meridian-logistics.example/hooks/test",
            "https://evil.example.com/hooks/test",
            "https://meridian-logistics.example.evil.com/test",
            "http://192.168.1.1/test",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                status, body = _get(self.port, f"/api/reports/daily?callback_url={urllib.parse.quote(url)}", TEST_TOKEN)
                self.assertEqual(status, 400)
                self.assertEqual(body["error"], "invalid callback_url")

    def test_daily_report_callback_url_valid(self) -> None:
        valid_urls = [
            "https://ops.meridian-logistics.example/hooks/probe",
            "https://meridian-logistics.example/hooks/test",
            "http://127.0.0.1:8000/callback",
            "http://localhost:8000/callback",
            "http://[::1]:8000/callback"
        ]
        
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            
            # Return a mock response for the callback
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect) as mock_urlopen:
            for url in valid_urls:
                with self.subTest(url=url):
                    mock_urlopen.reset_mock()
                    status, body = _get(self.port, f"/api/reports/daily?callback_url={urllib.parse.quote(url)}", TEST_TOKEN)
                    self.assertEqual(status, 200)
                    
                    # Verify that a request was made to the callback URL
                    callback_called = False
                    for call in mock_urlopen.call_args_list:
                        req_arg = call[0][0]
                        req_url = req_arg if isinstance(req_arg, str) else req_arg.full_url
                        if req_url == url:
                            callback_called = True
                            self.assertEqual(req_arg.method, "POST")
                            self.assertEqual(req_arg.headers["Content-type"], "application/json")
                            self.assertEqual(json.loads(req_arg.data.decode("utf-8"))["total_skus"], len(INVENTORY))
                    
                    self.assertTrue(callback_called, f"Callback to {url} was not made")

            self.assertEqual(
                body["low_stock"],
                [
                    {"sku": sku, "on_hand": INVENTORY[sku]}
                    for sku in sorted(INVENTORY)
                    if INVENTORY[sku] < 20
                ],
            )

    def test_daily_report_fields_subset(self) -> None:
        status, body = _get(
            self.port, "/api/reports/daily?fields=total_skus,low_stock", TEST_TOKEN
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.keys()), {"total_skus", "low_stock"})
        self.assertEqual(body["total_skus"], len(INVENTORY))
        self.assertEqual(
            body["low_stock"],
            [
                {"sku": sku, "on_hand": INVENTORY[sku]}
                for sku in sorted(INVENTORY)
                if INVENTORY[sku] < 20
            ],
        )

    def test_daily_report_fields_invalid(self) -> None:
        status, body = _get(self.port, "/api/reports/daily?fields=total_skus,nope", TEST_TOKEN)
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid fields"})

    def test_daily_report_format_template(self) -> None:
        status, body = _get(
            self.port,
            "/api/reports/daily?format=Inventory+on+{date}:+{total_skus}+total",
            TEST_TOKEN,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            body,
            f"Inventory on {datetime.now(timezone.utc).date().isoformat()}: {len(INVENTORY)} total",
        )

    def test_daily_report_format_invalid(self) -> None:
        status, body = _get(
            self.port, "/api/reports/daily?format=Inventory+on+{unknown}", TEST_TOKEN
        )
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid format"})


if __name__ == "__main__":
    unittest.main()
