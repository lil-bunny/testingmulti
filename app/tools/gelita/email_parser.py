"""Parse Gelita carrier email bodies for business keys and ack classification."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from app.configs import gelita_config
from app.core.logger import get_logger
from app.models.status import StatusSubType
from app.tools.llm_client import LLMClientError, chat_json

logger = get_logger(__name__)

_CARRIER_ACK_DECISIONS = frozenset(
    {
        StatusSubType.ACCEPTED.value,
        StatusSubType.REJECTED.value,
        StatusSubType.DO_NOTHING.value,
    }
)

_ORDER_NUMBER_RE = re.compile(r"Order\s*#\s*(\d+)", re.IGNORECASE)
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


def normalize_carrier_reply_body(
    *,
    body: str | None = None,
    body_plain: str | None = None,
) -> str:
    """
    Plain reply text for LLM: prefer ``body_plain``, else strip HTML/quotes from ``body``.
    """
    plain = (body_plain or "").strip()
    if plain:
        return _collapse_ws(_strip_quoted_plain(plain))

    raw = (body or "").strip()
    if not raw:
        return ""

    if "<" in raw:
        raw = _strip_quoted_html(raw)
        text = _strip_html(raw)
    else:
        text = _strip_quoted_plain(raw)

    return _collapse_ws(text)


def _normalize_carrier_ack_decision(raw: dict[str, Any]) -> str:
    """Map LLM output to ``accepted`` | ``rejected`` | ``do_nothing``."""
    decision = str(raw.get("decision") or "").strip().lower()
    if decision in _CARRIER_ACK_DECISIONS:
        return decision
    if bool(raw.get("is_acknowledgment")):
        return StatusSubType.ACCEPTED.value
    return StatusSubType.DO_NOTHING.value


def classify_carrier_acknowledgment(reply_text: str) -> dict[str, Any]:
    """
    LLM gate for carrier ack replies.

    Returns ``decision`` (``accepted`` | ``rejected`` | ``do_nothing``), ``confidence``, ``reason``.
    """
    text = (reply_text or "").strip()
    if not text:
        return {
            "decision": StatusSubType.DO_NOTHING.value,
            "confidence": 1.0,
            "reason": "empty reply body",
        }

    try:
        raw = chat_json(
            gelita_config.CARRIER_ACK_SYSTEM_PROMPT,
            text,
            temperature=0.1,
        )
    except LLMClientError as exc:
        logger.warning("carrier ack LLM failed: %s", exc)
        return {
            "decision": StatusSubType.DO_NOTHING.value,
            "confidence": 0.0,
            "reason": f"llm_error: {exc}",
        }

    decision = _normalize_carrier_ack_decision(raw)
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(raw.get("reason") or "").strip() or "no reason"

    return {
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
    }


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
