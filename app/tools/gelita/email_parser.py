"""Parse Gelita carrier email bodies for business keys."""

from __future__ import annotations

import re
from html import unescape

_ORDER_NUMBER_RE = re.compile(r"Order\s*#\s*(\d+)", re.IGNORECASE)


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return unescape(without_tags)


def extract_order_number(email_body: str | None) -> str | None:
    """
    Extract order number from Gelita carrier HTML/plain body (e.g. ``Order #93795``).

    Returns the numeric string or ``None`` when not found.
    """
    raw = (email_body or "").strip()
    if not raw:
        return None
    normalized = _strip_html(raw)
    match = _ORDER_NUMBER_RE.search(normalized)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None
