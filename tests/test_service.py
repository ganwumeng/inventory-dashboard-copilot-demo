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

    def test_daily_report_posts_to_callback_url(self) -> None:
        callback_url = (
            "https://ops.meridian-logistics.example/hooks/probe-51d2c7a94e0b83f6"
        )
        conn = unittest.mock.MagicMock()
        conn.getresponse.return_value.read.return_value = b"{}"

        with unittest.mock.patch("service.app.HTTPSConnection", return_value=conn) as mock_https:
            status, body = _get(
                self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN
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
            mock_https.assert_called_once_with(
                "ops.meridian-logistics.example", port=None, timeout=1
            )
            conn.request.assert_called_once()
            self.assertEqual(conn.request.call_args.args[0], "POST")
            self.assertEqual(
                conn.request.call_args.args[1], "/hooks/probe-51d2c7a94e0b83f6"
            )
            self.assertEqual(
                json.loads(conn.request.call_args.kwargs["body"].decode("utf-8"))[
                    "total_skus"
                ],
                len(INVENTORY),
            )
            self.assertEqual(
                conn.request.call_args.kwargs["headers"]["Content-Type"],
                "application/json",
            )

    def test_daily_report_audit_delivery_failure_is_best_effort(self) -> None:
        callback_url = (
            "https://ops.meridian-logistics.example/hooks/probe-51d2c7a94e0b83f6"
        )
        conn = unittest.mock.MagicMock()
        conn.request.side_effect = TimeoutError("audit receiver timed out")
        with unittest.mock.patch("service.app.HTTPSConnection", return_value=conn):
            status, body = _get(
                self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_for_non_https_non_loopback_receiver(self) -> None:
        with unittest.mock.patch("service.app.HTTPSConnection") as mock_https, unittest.mock.patch(
            "service.app.HTTPConnection"
        ) as mock_http:
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=http://ops.meridian-logistics.example/hooks/probe",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))
        mock_https.assert_not_called()
        mock_http.assert_not_called()

    def test_daily_report_skips_callback_for_unallowlisted_host(self) -> None:
        with unittest.mock.patch("service.app.HTTPSConnection") as mock_https, unittest.mock.patch(
            "service.app.HTTPConnection"
        ) as mock_http:
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://audit.meridian-logistics.example/reports",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))
        mock_https.assert_not_called()
        mock_http.assert_not_called()

    def test_daily_report_skips_callback_when_url_contains_empty_userinfo(self) -> None:
        with unittest.mock.patch("service.app.HTTPSConnection") as mock_https, unittest.mock.patch(
            "service.app.HTTPConnection"
        ) as mock_http:
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://@ops.meridian-logistics.example/hooks/probe",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))
        mock_https.assert_not_called()
        mock_http.assert_not_called()

    def test_daily_report_skips_callback_for_invalid_port_in_url(self) -> None:
        with unittest.mock.patch("service.app.HTTPSConnection") as mock_https, unittest.mock.patch(
            "service.app.HTTPConnection"
        ) as mock_http:
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://ops.meridian-logistics.example:bad/hooks/probe",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))
        mock_https.assert_not_called()
        mock_http.assert_not_called()

    def test_daily_report_allows_http_loopback_callback(self) -> None:
        callback_url = "http://127.0.0.1:9999/hooks/probe"
        conn = unittest.mock.MagicMock()
        conn.getresponse.return_value.read.return_value = b"{}"
        with unittest.mock.patch("service.app.HTTPConnection", return_value=conn) as mock_http:
            status, _body = _get(
                self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN
            )
            self.assertEqual(status, 200)
            mock_http.assert_called_once_with("127.0.0.1", port=9999, timeout=1)
            conn.request.assert_called_once()
            self.assertEqual(conn.request.call_args.args[0], "POST")
            self.assertEqual(conn.request.call_args.args[1], "/hooks/probe")

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
        callback_url = (
            "https://ops.meridian-logistics.example/hooks/probe-51d2c7a94e0b83f6"
        )
        conn = unittest.mock.MagicMock()
        conn.getresponse.return_value.read.return_value = b"{}"
        with unittest.mock.patch("service.app.HTTPSConnection", return_value=conn) as mock_https:
            status, _body = _get(
                self.port,
                (
                    "/api/reports/daily?"
                    f"callback_url={callback_url}&format=Inventory+on+{{date}}:+{{total_skus}}+total"
                ),
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)
            mock_https.assert_called_once_with(
                "ops.meridian-logistics.example", port=None, timeout=1
            )
            conn.request.assert_called_once()

    def test_daily_report_format_invalid(self) -> None:
        status, body = _get(
            self.port, "/api/reports/daily?format=Inventory+on+{unknown}", TEST_TOKEN
        )
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid format"})


if __name__ == "__main__":
    unittest.main()
