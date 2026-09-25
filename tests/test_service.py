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


def _get(
    port: int,
    path: str,
    token: str | None = None,
    gateway_token: str | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    if gateway_token is not None:
        request.add_header("X-Gateway-Token", gateway_token)
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

    def test_daily_report_posts_to_fixed_audit_receiver(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect) as mock_urlopen:
            status, body = _get(self.port, "/api/reports/daily", TEST_TOKEN)
            self.assertEqual(status, 200)
            self.assertEqual(
                body["low_stock"],
                [
                    {"sku": sku, "on_hand": INVENTORY[sku]}
                    for sku in sorted(INVENTORY)
                    if INVENTORY[sku] < 20
                ],
            )

            audit_calls = []
            for call in mock_urlopen.call_args_list:
                req_arg = call[0][0]
                req_url = req_arg if isinstance(req_arg, str) else req_arg.full_url
                if req_url == "https://audit.meridian-logistics.example/reports":
                    audit_calls.append(req_arg)

            self.assertEqual(len(audit_calls), 1)
            self.assertEqual(audit_calls[0].method, "POST")
            self.assertEqual(audit_calls[0].headers["Content-type"], "application/json")
            self.assertEqual(
                json.loads(audit_calls[0].data.decode("utf-8"))["total_skus"],
                len(INVENTORY),
            )

    def test_daily_report_audit_delivery_failure_is_best_effort(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str == "https://audit.meridian-logistics.example/reports":
                raise TimeoutError("audit receiver timed out")
            return original_urlopen(req, *args, **kwargs)

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(self.port, "/api/reports/daily", TEST_TOKEN)

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_audit_post_for_non_https_receiver(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch(
            "service.app.AUDIT_REPORT_RECEIVER_URL",
            "http://audit.meridian-logistics.example/reports",
        ), unittest.mock.patch(
            "urllib.request.urlopen", side_effect=urlopen_side_effect
        ):
            status, body = _get(self.port, "/api/reports/daily", TEST_TOKEN)

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_audit_post_for_unallowlisted_host(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch(
            "service.app.AUDIT_REPORT_RECEIVER_URL",
            "https://ops.meridian-logistics.example/reports",
        ), unittest.mock.patch(
            "urllib.request.urlopen", side_effect=urlopen_side_effect
        ):
            status, body = _get(self.port, "/api/reports/daily", TEST_TOKEN)

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

    def test_daily_report_format_template_posts_to_fixed_audit_receiver(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect) as mock_urlopen:
            status, _body = _get(
                self.port,
                "/api/reports/daily?format=Inventory+on+{date}:+{total_skus}+total",
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)

            audit_calls = []
            for call in mock_urlopen.call_args_list:
                req_arg = call[0][0]
                req_url = req_arg if isinstance(req_arg, str) else req_arg.full_url
                if req_url == "https://audit.meridian-logistics.example/reports":
                    audit_calls.append(req_arg)

            self.assertEqual(len(audit_calls), 1)
            self.assertEqual(audit_calls[0].method, "POST")
            self.assertEqual(audit_calls[0].headers["Content-type"], "application/json")

    def test_daily_report_format_invalid(self) -> None:
        status, body = _get(
            self.port, "/api/reports/daily?format=Inventory+on+{unknown}", TEST_TOKEN
        )
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid format"})

    def test_gateway_token_bypasses_bearer_auth(self) -> None:
        gateway_token = "probe-d6b182f4c7093e5a"
        sku = sorted(INVENTORY)[0]

        # GET /api/reports/daily with X-Gateway-Token
        status, body = _get(self.port, "/api/reports/daily", gateway_token=gateway_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

        # GET /api/inventory/count with X-Gateway-Token
        status, body = _get(self.port, "/api/inventory/count", gateway_token=gateway_token)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sku_count": len(INVENTORY)})

        # GET /api/inventory/<sku> with X-Gateway-Token
        status, body = _get(self.port, f"/api/inventory/{sku}", gateway_token=gateway_token)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"sku": sku, "on_hand": INVENTORY[sku]})

    def test_invalid_gateway_token_fails_without_bearer(self) -> None:
        status, _ = _get(self.port, "/api/reports/daily", gateway_token="invalid-probe-token")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
