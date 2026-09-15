"""CLI entry point: ``python3 run.py [--port N]``.

The bearer token is read from the ``DASHBOARD_TOKEN`` environment variable.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from service.app import create_app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the inventory dashboard service."
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="port to bind (0 = ephemeral)"
    )
    args = parser.parse_args(argv)
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token:
        print("DASHBOARD_TOKEN environment variable is required", file=sys.stderr)
        return 2
    server = create_app(token, port=args.port)
    host, bound_port = server.server_address[:2]
    print(f"dashboard service listening on http://{host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
