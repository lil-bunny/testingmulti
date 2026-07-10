"""Registry of async handlers for the email webhook Celery task."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

HANDLER_INBOUND_UNIPILE_EMAIL = "inbound.unipile_email"

EmailWebhookHandler = Callable[..., Awaitable[Any]]


def get_email_webhook_handler(handler: str) -> EmailWebhookHandler:
    """
    Resolve Celery handler by key.

    Lazy import of ``process_inbound_unipile_email`` avoids import cycles between
    enqueue (API) and ingress services at worker startup.
    """
    if handler == HANDLER_INBOUND_UNIPILE_EMAIL:
        from app.services.inbound_unipile_email_handler import process_inbound_unipile_email

        return process_inbound_unipile_email
    raise ValueError(f"unknown email webhook handler: {handler!r}")
