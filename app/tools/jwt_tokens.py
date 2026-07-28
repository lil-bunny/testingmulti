"""JWT helpers for reading token metadata (expiry only — not authZ)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt


def _decode_unverified_payload(token: str) -> dict[str, Any] | None:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw or raw.count(".") < 2:
        return None
    try:
        payload = jwt.decode(
            raw,
            options={"verify_signature": False},
            algorithms=["HS256", "HS384", "HS512", "RS256", "RS384", "RS512"],
        )
    except jwt.PyJWTError:
        return None
    return payload if isinstance(payload, dict) else None


def expires_at_from_bearer_token(token: str) -> datetime | None:
    """Return UTC expiry from JWT ``exp`` claim, or None if unavailable."""
    payload = _decode_unverified_payload(token)
    if not payload:
        return None
    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return None
    if exp_int <= 0:
        return None
    return datetime.fromtimestamp(exp_int, tz=timezone.utc)
