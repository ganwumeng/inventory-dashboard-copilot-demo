"""HTTP dashboard service built on ``http.server``.

``create_app(token)`` returns a ``ThreadingHTTPServer`` bound to an
ephemeral port on 127.0.0.1; read the bound port from
``server.server_address[1]``. The bearer token is passed explicitly; this
package never reads environment variables.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlunparse

from . import auth, store


CALLBACK_URL_HTTPS_ALLOWLIST = frozenset({"ops.meridian-logistics.example"})
CALLBACK_URL_HTTP_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def _safe_callback_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    path = parsed.path or "/"
    query = parsed.query

    if parsed.scheme == "https":
        if parsed.hostname not in CALLBACK_URL_HTTPS_ALLOWLIST or port not in (None, 443):
            return None
        return urlunparse(
            ("https", "ops.meridian-logistics.example", path, "", query, "")
        )
    if parsed.scheme == "http":
        if parsed.hostname not in CALLBACK_URL_HTTP_LOOPBACK:
            return None
        if parsed.hostname == "::1":
            host = "[::1]"
        else:
            host = parsed.hostname
        netloc = f"{host}:{port}" if port is not None else host
        return urlunparse(("http", netloc, path, "", query, ""))
    return None


def create_app(token: str, *, port: int = 0) -> ThreadingHTTPServer:
    """Create the dashboard HTTP server bound to 127.0.0.1:``port``."""

    if not token:
        raise ValueError("token must not be empty")

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "DashboardService/1.0"

        def _send_json(self, status: int, value: object) -> None:
            payload = (json.dumps(value) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            return auth.token_valid(self.headers.get("Authorization"), token)

        def _post_daily_report_audit(
            self, report: dict[str, object], callback_url: str | None
        ) -> None:
            safe_callback_url = (
                _safe_callback_url(callback_url) if callback_url else None
            )
            if not safe_callback_url:
                return
            try:
                req = urllib.request.Request(
                    safe_callback_url,
                    data=json.dumps(report).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=1) as _resp:
                    pass
            except Exception:
                pass

        def do_GET(self) -> None:  # noqa: N802 -- http.server handler API
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)

            if path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if path == "/api/reports/daily":
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"})
                    return

                report = {
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "total_skus": len(store.INVENTORY),
                    "low_stock": [
                        {"sku": sku, "on_hand": store.INVENTORY[sku]}
                        for sku in sorted(store.INVENTORY)
                        if store.INVENTORY[sku] < 20
                    ],
                }
                callback_url = query.get("callback_url", [None])[0]
                self._post_daily_report_audit(report, callback_url)
                self._send_json(200, report)
                return
            if path == "/api/inventory/count":
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"})
                    return
                self._send_json(200, {"sku_count": len(store.INVENTORY)})
                return
            if path.startswith("/api/inventory/"):
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"})
                    return
                sku = path[len("/api/inventory/"):]
                if sku not in store.INVENTORY:
                    self._send_json(404, {"error": "unknown sku"})
                    return
                self._send_json(
                    200, {"sku": sku, "on_hand": store.INVENTORY[sku]}
                )
                return
            self._send_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            pass  # keep test output quiet

    return ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
