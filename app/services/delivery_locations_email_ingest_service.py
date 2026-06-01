"""Celery worker: ingest delivery_location.xlsx from Gelita email webhook."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.services.email_webhook_attachment_ingestion import (
    process_delivery_locations_attachment_import,
)

logger = get_logger(__name__)

WORKFLOW_NAME = "load_tendering"


async def process_delivery_locations_from_email_webhook(
    *,
    payload: dict[str, Any],
    tenant_uuid: str,
) -> dict[str, Any]:
    """Fetch delivery locations workbook and upsert ``data_imports``."""
    data_import_id = await process_delivery_locations_attachment_import(
        payload=payload,
        workflow_name=WORKFLOW_NAME,
        data_import_tenant_id=tenant_uuid,
    )
    if not data_import_id:
        raise RuntimeError(
            "delivery locations ingest: no data_import_id "
            "(missing delivery_location.xlsx or fetch failed)"
        )

    logger.info(
        "delivery locations ingest complete tenant_id=%s data_import_id=%s",
        tenant_uuid,
        data_import_id,
    )
    return {
        "message": "success",
        "event_type": "delivery_locations_updated",
        "data_import_id": data_import_id,
    }
