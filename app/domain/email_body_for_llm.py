"""Plain email body normalization for LLM input (pure, no I/O)."""

from __future__ import annotations

import re
from html import unescape

_QUOTE_HTML_RE = re.compile(r'<div[^>]*class="[^"]*gmail_quote', re.IGNORECASE)
_BLOCKQUOTE_RE = re.compile(r"<blockquote\b", re.IGNORECASE)
_ON_WROTE_RE = re.compile(r"\bOn .+ wrote:\s*", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return unescape(without_tags)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _strip_quoted_html(html: str) -> str:
    for pattern in (_QUOTE_HTML_RE, _BLOCKQUOTE_RE):
        match = pattern.search(html)
        if match:
            return html[: match.start()].strip()
    return html


def _strip_quoted_plain(text: str) -> str:
    match = _ON_WROTE_RE.search(text)
    if match:
        return text[: match.start()].strip()
    return text


def normalize_email_body_for_llm(*, body: str | None = None) -> str:
    """Plain email text for LLM input: strip HTML/quotes from ``body``."""
    raw = (body or "").strip()
    if not raw:
        return ""

    if "<" in raw:
        raw = _strip_quoted_html(raw)
        text = _strip_html(raw)
    else:
        text = _strip_quoted_plain(raw)

    return _collapse_ws(text)
