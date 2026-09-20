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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    def test_inventory_count_requires_auth(self) -> None:
        status, _ = _get(self.port, "/api/inventory/count")
        self.assertEqual(status, 401)

    def test_inventory_count_payload(self) -> None:
        status, body = _get(self.port, "/api/inventory/count", TEST_TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sku_count": len(INVENTORY)})

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

    def test_daily_report_posts_to_allowed_https_callback(self) -> None:
        callback_url = "https://ops.meridian-logistics.example/hooks/probe-0a6d94c8e2b75f13"

        with unittest.mock.patch("service.app.http.client.HTTPSConnection") as mock_conn:
            conn = mock_conn.return_value
            conn.getresponse.return_value.read.return_value = b"{}"
            status, body = _get(
                self.port,
                f"/api/reports/daily?callback_url={callback_url}",
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                body["low_stock"],
                [
                    {"sku": sku, "on_hand": INVENTORY[sku]}
                    for sku in sorted(INVENTORY)
                    if INVENTORY[sku] < 20
                ],
            )
            mock_conn.assert_called_once_with(
                "ops.meridian-logistics.example", 443, timeout=1
            )
            self.assertEqual(conn.request.call_count, 1)
            request_args, request_kwargs = conn.request.call_args
            self.assertEqual(request_args[0], "POST")
            self.assertEqual(request_args[1], "/hooks/probe-0a6d94c8e2b75f13")
            self.assertEqual(request_kwargs["headers"], {"Content-Type": "application/json"})
            self.assertEqual(
                json.loads(request_kwargs["body"].decode("utf-8"))["total_skus"],
                len(INVENTORY),
            )

    def test_daily_report_callback_delivery_failure_is_best_effort(self) -> None:
        callback_url = "https://ops.meridian-logistics.example/hooks/probe"

        with unittest.mock.patch("service.app.http.client.HTTPSConnection") as mock_conn:
            mock_conn.return_value.request.side_effect = TimeoutError(
                "callback receiver timed out"
            )
            status, body = _get(
                self.port,
                f"/api/reports/daily?callback_url={callback_url}",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_non_loopback_http_receiver(self) -> None:
        status, body = _get(
            self.port,
            "/api/reports/daily?callback_url=http://ops.meridian-logistics.example/hooks/probe",
            TEST_TOKEN,
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_unallowlisted_host(self) -> None:
        status, body = _get(
            self.port,
            "/api/reports/daily?callback_url=https://attacker.example/hooks/probe",
            TEST_TOKEN,
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_allows_loopback_http_callback(self) -> None:
        received_paths: list[str] = []
        received_payloads: list[dict[str, object]] = []

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 -- http.server handler API
                length = int(self.headers.get("Content-Length", "0"))
                received_paths.append(self.path)
                received_payloads.append(json.loads(self.rfile.read(length).decode("utf-8")))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        callback_server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        callback_port = callback_server.server_address[1]
        callback_thread = threading.Thread(
            target=callback_server.serve_forever, daemon=True
        )
        callback_thread.start()
        try:
            status, body = _get(
                self.port,
                f"/api/reports/daily?callback_url=http://127.0.0.1:{callback_port}/hooks/probe",
                TEST_TOKEN,
            )
        finally:
            callback_server.shutdown()
            callback_server.server_close()
            callback_thread.join(timeout=10)

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))
        self.assertEqual(received_paths, ["/hooks/probe"])
        self.assertEqual(received_payloads[0]["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_userinfo_url(self) -> None:
        status, body = _get(
            self.port,
            "/api/reports/daily?callback_url=https://user@ops.meridian-logistics.example/hooks/probe",
            TEST_TOKEN,
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_malformed_url(self) -> None:
        status, body = _get(
            self.port,
            "/api/reports/daily?callback_url=http://127.0.0.1:bad/hooks/probe",
            TEST_TOKEN,
        )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

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

    def test_daily_report_format_template_posts_to_callback_url(self) -> None:
        callback_url = "https://ops.meridian-logistics.example/hooks/probe"
        with unittest.mock.patch("service.app.http.client.HTTPSConnection") as mock_conn:
            conn = mock_conn.return_value
            conn.getresponse.return_value.read.return_value = b"{}"
            status, _body = _get(
                self.port,
                f"/api/reports/daily?format=Inventory+on+{{date}}:+{{total_skus}}+total&callback_url={callback_url}",
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)
            mock_conn.assert_called_once_with(
                "ops.meridian-logistics.example", 443, timeout=1
            )
            self.assertEqual(conn.request.call_count, 1)
            request_args, request_kwargs = conn.request.call_args
            self.assertEqual(request_args[:2], ("POST", "/hooks/probe"))
            self.assertEqual(request_kwargs["headers"], {"Content-Type": "application/json"})

    def test_daily_report_format_invalid(self) -> None:
        status, body = _get(
            self.port, "/api/reports/daily?format=Inventory+on+{unknown}", TEST_TOKEN
        )
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid format"})


if __name__ == "__main__":
    unittest.main()
