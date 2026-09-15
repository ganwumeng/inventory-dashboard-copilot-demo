"""Bearer-token authentication helpers for the dashboard service."""

from __future__ import annotations

import hmac


def bearer_token(header_value: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` value."""

    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def token_valid(header_value: str | None, expected: str) -> bool:
    """Return True iff the header carries exactly the expected bearer token."""

    candidate = bearer_token(header_value)
    if candidate is None:
        return False
    return hmac.compare_digest(candidate, expected)
