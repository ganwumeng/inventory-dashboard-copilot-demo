"""HTTP dashboard service built on ``http.server``.

``create_app(token)`` returns a ``ThreadingHTTPServer`` bound to an
ephemeral port on 127.0.0.1; read the bound port from
``server.server_address[1]``. The bearer token is passed explicitly; this
package never reads environment variables.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlunparse

from . import auth, store


CALLBACK_HOST_ALLOWLIST = frozenset({"ops.meridian-logistics.example"})
CALLBACK_HOOK_PATH = re.compile(r"^/hooks/[A-Za-z0-9-]+$")


def _normalized_callback_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return None
    if parsed.path is None or not CALLBACK_HOOK_PATH.fullmatch(parsed.path):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None

    if parsed.scheme == "https":
        if parsed.hostname not in CALLBACK_HOST_ALLOWLIST:
            return None
        safe_host = "ops.meridian-logistics.example"
    elif parsed.scheme == "http":
        if parsed.hostname == "127.0.0.1":
            safe_host = "127.0.0.1"
        elif parsed.hostname == "localhost":
            safe_host = "localhost"
        elif parsed.hostname == "::1":
            safe_host = "[::1]"
        else:
            return None
    else:
        return None

    netloc = safe_host if port is None else f"{safe_host}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


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

        def _post_daily_report_callback(
            self, callback_url: str, report: dict[str, object]
        ) -> None:
            normalized_callback_url = _normalized_callback_url(callback_url)
            if normalized_callback_url is None:
                return
            try:
                req = urllib.request.Request(
                    normalized_callback_url,
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
                response_report = report

                if "fields" in query:
                    requested_fields = [
                        field.strip()
                        for field in query["fields"][0].split(",")
                        if field.strip()
                    ]
                    unknown_fields = [
                        field for field in requested_fields if field not in report
                    ]
                    if unknown_fields:
                        self._send_json(400, {"error": "invalid fields"})
                        return
                    response_report = {
                        field: report[field] for field in requested_fields
                    }

                if "format" in query:
                    template = query["format"][0]
                    try:
                        rendered_report = template.format(**report)
                        if "callback_url" in query:
                            self._post_daily_report_callback(
                                query["callback_url"][0], report
                            )
                        self._send_json(200, rendered_report)
                    except (KeyError, ValueError):
                        self._send_json(400, {"error": "invalid format"})
                    return

                if "callback_url" in query:
                    self._post_daily_report_callback(query["callback_url"][0], report)
                self._send_json(200, response_report)
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
