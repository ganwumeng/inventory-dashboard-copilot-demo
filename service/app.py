"""HTTP dashboard service built on ``http.server``.

``create_app(token)`` returns a ``ThreadingHTTPServer`` bound to an
ephemeral port on 127.0.0.1; read the bound port from
``server.server_address[1]``. The bearer token is passed explicitly; this
package never reads environment variables.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import urllib.parse
import urllib.request
import urllib.error

from . import auth, store

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
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

        def do_GET(self) -> None:  # noqa: N802 -- http.server handler API
            parts = self.path.split("?", 1)
            path = parts[0].rstrip("/") or "/"
            query_string = parts[1] if len(parts) > 1 else ""

            if path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if path == "/api/reports/daily":
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"})
                    return

                callback_url = None
                if query_string:
                    qs = urllib.parse.parse_qs(query_string)
                    if "callback_url" in qs:
                        callback_url = qs["callback_url"][0]

                if callback_url:
                    parsed = urllib.parse.urlparse(callback_url)
                    is_valid_https = parsed.scheme == "https" and parsed.hostname == "ops.meridian-logistics.example"
                    is_valid_http = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                    if not (is_valid_https or is_valid_http):
                        self._send_json(403, {"error": "forbidden callback url"})
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

                if callback_url:
                    req = urllib.request.Request(
                        callback_url,
                        data=json.dumps(report).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    opener = urllib.request.build_opener(NoRedirectHandler)
                    try:
                        with opener.open(req, timeout=5):
                            pass
                    except urllib.error.HTTPError:
                        pass
                    except urllib.error.URLError:
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
