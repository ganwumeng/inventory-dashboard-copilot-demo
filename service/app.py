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
from urllib.parse import parse_qs, urlparse

from . import auth, store

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

                if "callback_url" in query:
                    callback_url = query["callback_url"][0]
                    cb_parsed = urlparse(callback_url)
                    is_safe = False
                    if cb_parsed.scheme == "https" and cb_parsed.hostname:
                        if cb_parsed.hostname == "meridian-logistics.example" or cb_parsed.hostname.endswith(".meridian-logistics.example"):
                            is_safe = True
                    elif cb_parsed.scheme == "http" and cb_parsed.hostname in ("127.0.0.1", "localhost", "::1"):
                        is_safe = True

                    if not is_safe:
                        self._send_json(400, {"error": "invalid callback_url"})
                        return

                    try:
                        req = urllib.request.Request(
                            callback_url,
                            data=json.dumps(report).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=5) as _resp:
                            pass
                    except Exception:
                        pass

                self._send_json(200, report)
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
