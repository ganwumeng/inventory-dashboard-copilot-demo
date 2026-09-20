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

    def test_daily_report_posts_to_callback_url_when_allowed_https(self) -> None:
        original_urlopen = urllib.request.urlopen
        callback_url = "https://ops.meridian-logistics.example/hooks/probe-7e06b1d4a5c92f38"

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=urlopen_side_effect
        ) as mock_urlopen:
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

            callback_calls = []
            for call in mock_urlopen.call_args_list:
                req_arg = call[0][0]
                req_url = req_arg if isinstance(req_arg, str) else req_arg.full_url
                if req_url == callback_url:
                    callback_calls.append(req_arg)

            self.assertEqual(len(callback_calls), 1)
            self.assertEqual(callback_calls[0].method, "POST")
            self.assertEqual(
                callback_calls[0].headers["Content-type"], "application/json"
            )
            self.assertEqual(
                json.loads(callback_calls[0].data.decode("utf-8"))["total_skus"],
                len(INVENTORY),
            )

    def test_daily_report_callback_delivery_failure_is_best_effort(self) -> None:
        original_urlopen = urllib.request.urlopen
        callback_url = "https://ops.meridian-logistics.example/hooks/probe-7e06b1d4a5c92f38"

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str == callback_url:
                raise TimeoutError("callback receiver timed out")
            return original_urlopen(req, *args, **kwargs)

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(
                self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_posts_to_callback_url_when_http_loopback(self) -> None:
        original_urlopen = urllib.request.urlopen
        callback_url = "http://127.0.0.1:8989/hooks/probe-local"

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)

            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"{}"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=urlopen_side_effect
        ) as mock_urlopen:
            status, body = _get(
                self.port, f"/api/reports/daily?callback_url={callback_url}", TEST_TOKEN
            )

            self.assertEqual(status, 200)
            self.assertEqual(body["total_skus"], len(INVENTORY))
            callback_calls = []
            for call in mock_urlopen.call_args_list:
                req_arg = call[0][0]
                req_url = req_arg if isinstance(req_arg, str) else req_arg.full_url
                if req_url == callback_url:
                    callback_calls.append(req_arg)
            self.assertEqual(len(callback_calls), 1)

    def test_daily_report_skips_callback_post_for_non_loopback_http_host(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=http://ops.meridian-logistics.example/hooks/probe",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_unallowlisted_https_host(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://example.com/hooks/probe",
                TEST_TOKEN,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_userinfo_url(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://user@ops.meridian-logistics.example/hooks/probe",
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["total_skus"], len(INVENTORY))

    def test_daily_report_skips_callback_post_for_malformed_port(self) -> None:
        original_urlopen = urllib.request.urlopen

        def urlopen_side_effect(req, *args, **kwargs):
            url_str = req if isinstance(req, str) else req.full_url
            if url_str.startswith(f"http://127.0.0.1:{self.port}"):
                return original_urlopen(req, *args, **kwargs)
            raise AssertionError(f"unexpected outbound call: {url_str}")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            status, body = _get(
                self.port,
                "/api/reports/daily?callback_url=https://ops.meridian-logistics.example:bad/hooks/probe",
                TEST_TOKEN,
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["total_skus"], len(INVENTORY))


if __name__ == "__main__":
    unittest.main()
