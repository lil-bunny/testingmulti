"""Extract business keys from Gelita carrier email bodies."""

from __future__ import annotations

import re
from html import unescape

_ORDER_NUMBER_RE = re.compile(r"Order\s*#\s*(\d+)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return unescape(without_tags)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def extract_order_number(email_body: str | None) -> str | None:
    """
    Extract order number from Gelita carrier HTML/plain body (e.g. ``Order #93795``).

    Unlike LLM normalization, quoted/forwarded HTML is kept so ``Order #`` inside
    Gmail ``gmail_quote`` blocks still matches.

    Returns the numeric string or ``None`` when not found.
    """
    raw = (email_body or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if "<" in raw:
        candidates.append(_collapse_ws(_strip_html(raw)))

    for candidate in candidates:
        match = _ORDER_NUMBER_RE.search(candidate)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None
