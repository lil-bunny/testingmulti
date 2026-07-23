"""Microsoft Teams Incoming Webhook (Office 365 Connector MessageCard)."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 30.0


class TeamsWebhookError(Exception):
    """Raised when Teams webhook returns a non-2xx response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _redact_webhook_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if len(text) <= 24:
        return "***"
    return f"{text[:12]}...{text[-4:]}"


def build_message_card_payload(
    *,
    title: str,
    text: str,
    facts: list[tuple[str, str]],
) -> dict[str, Any]:
    section: dict[str, Any] = {"text": text}
    if facts:
        section["facts"] = [{"name": name, "value": value} for name, value in facts]
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "C2272D",
        "title": title,
        "sections": [section],
    }


async def post_message_card(
    webhook_url: str,
    *,
    title: str,
    text: str,
    facts: list[tuple[str, str]],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> None:
    """POST a MessageCard to a Teams Incoming Webhook URL."""
    url = (webhook_url or "").strip()
    if not url:
        raise TeamsWebhookError("teams webhook url is required")

    payload = build_message_card_payload(title=title, text=text, facts=facts)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning(
            "teams webhook request failed url=%s error=%s",
            _redact_webhook_url(url),
            exc,
        )
        raise TeamsWebhookError(f"teams webhook request failed: {exc}") from exc

    if 200 <= resp.status_code < 300:
        return

    body_snippet = (resp.text or "")[:500]
    logger.warning(
        "teams webhook non-2xx url=%s status=%s body=%s",
        _redact_webhook_url(url),
        resp.status_code,
        body_snippet,
    )
    raise TeamsWebhookError(
        f"teams webhook returned {resp.status_code}",
        status_code=resp.status_code,
        body=body_snippet,
    )


def post_message_card_sync(
    webhook_url: str,
    *,
    title: str,
    text: str,
    facts: list[tuple[str, str]],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> None:
    """Sync facade for graph nodes and sync services."""
    run_sync(
        post_message_card(
            webhook_url,
            title=title,
            text=text,
            facts=facts,
            timeout_s=timeout_s,
        )
    )
