"""Registry of async handlers for the email webhook Celery task."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.delivery_locations_email_ingest_service import (
    process_delivery_locations_from_email_webhook,
)
from app.services.load_tendering_email_ingest_service import (
    process_tender_created_from_email_webhook,
)

HANDLER_LOAD_TENDERING_TENDER_CREATED = "load_tendering.tender_created"
HANDLER_DELIVERY_LOCATIONS_IMPORT = "load_tendering.delivery_locations"

EmailWebhookHandler = Callable[..., Awaitable[Any]]

HANDLERS: dict[str, EmailWebhookHandler] = {
    HANDLER_LOAD_TENDERING_TENDER_CREATED: process_tender_created_from_email_webhook,
    HANDLER_DELIVERY_LOCATIONS_IMPORT: process_delivery_locations_from_email_webhook,
}
