"""Extract business keys from Gelita carrier email bodies."""

from __future__ import annotations

import re

from app.services.communications._mapper import normalize_email_body_for_llm

_ORDER_NUMBER_RE = re.compile(r"Order\s*#\s*(\d+)", re.IGNORECASE)


def extract_order_number(email_body: str | None) -> str | None:
    """
    Extract order number from Gelita carrier HTML/plain body (e.g. ``Order #93795``).

    Returns the numeric string or ``None`` when not found.
    """
    raw = (email_body or "").strip()
    if not raw:
        return None
    normalized = normalize_email_body_for_llm(body=raw)
    match = _ORDER_NUMBER_RE.search(normalized)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None
