"""Background ingest: email xlsx → data_imports → tenders → load_tendering workflows."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.configs.gelita_delivery_locations_columns import (
    GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS,
)
from app.configs.load_tendering_import_projection import LOAD_TENDERING_ROW_PROJECTION
from app.core.logger import get_logger
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.services.delivery_locations_data_import import (
    load_delivery_location_rows_from_data_import,
)
from app.services.delivery_locations_service import DeliveryLocationsService
from app.services.email_import_projection import (
    load_email_data_import_projection,
    persist_tender_rows_from_email_import_projection,
)
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)

WORKFLOW_NAME = "load_tendering"


def enqueue_load_tendering_workflow(
    *,
    graph_slug: str,
    payload: dict[str, Any],
    event_type: str,
) -> str:
    execution_id = str(uuid.uuid4())
    body = {**payload, "event_type": event_type, "execution_id": execution_id}
    task = run_workflow_async.apply_async(
        kwargs={
            "tenant_slug": graph_slug,
            "workflow_name": WORKFLOW_NAME,
            "payload": body,
        }
    )
    logger.info(
        "load_tendering ingest queued workflow task_id=%s execution_id=%s event_type=%s",
        task.id,
        execution_id,
        event_type,
    )
    return execution_id


async def process_tender_created_from_email_webhook(
    *,
    payload: dict[str, Any],
    tenant_uuid: str,
    tenant_slug: str,
    graph_slug: str,
) -> dict[str, Any]:
    """
    Full tender_created pipeline (attachment → DB → per-row workflow enqueue).

    Celery worker entrypoint; not for HTTP handlers.
    """
    data_import_id = await process_email_webhook_attachment_import(
        payload=payload,
        workflow_name=WORKFLOW_NAME,
        data_import_tenant_id=tenant_uuid,
        data_import_data_type=DataImportDataType.LOAD_TENDER,
        ingest_source_type=DataImportSourceType.EMAIL,
        skip_fetch_if_existing=True,
    )
    if not data_import_id:
        raise RuntimeError(
            "load_tendering ingest: no data_import_id (missing attachment or fetch failed)"
        )

    projected_rows = load_email_data_import_projection(
        tenant_id=tenant_uuid,
        data_import_id=data_import_id,
        projection=LOAD_TENDERING_ROW_PROJECTION,
    )

    delivery_locations_service = DeliveryLocationsService(
        rows_provider=lambda: load_delivery_location_rows_from_data_import(tenant_uuid),
        column_mapping=GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS,
    )

    tender_ids_by_row = persist_tender_rows_from_email_import_projection(
        tenant_id=tenant_uuid,
        data_import_id=data_import_id,
        projected_rows=projected_rows,
        delivery_locations=delivery_locations_service,
    )

    shared_payload: dict[str, Any] = {**payload, "workflow_name": WORKFLOW_NAME}
    mail_thread_src = shared_payload.pop("thread_id", None)
    if mail_thread_src is not None:
        stripe = str(mail_thread_src).strip()
        if stripe:
            shared_payload["source_email_thread_id"] = stripe

    execution_ids: list[str] = []
    enqueued_tender_ids: set[str] = set()
    for row_index, tender_row in enumerate(projected_rows):
        tender_id = (
            tender_ids_by_row[row_index]
            if row_index < len(tender_ids_by_row)
            else None
        )
        if not tender_id:
            logger.info(
                "load_tendering tender_created: skip row (new tender not created) row_index=%s "
                "order_number=%r",
                row_index,
                tender_row.get("order_number"),
            )
            continue
        if tender_id in enqueued_tender_ids:
            logger.info(
                "load_tendering tender_created: skip duplicate order row row_index=%s tender_id=%s",
                row_index,
                tender_id,
            )
            continue
        enqueued_tender_ids.add(tender_id)

        from app.domain.load_tendering_state import set_tender, tender_from_ingest_row

        order_number = str(tender_row.get("order_number") or "").strip()
        workflow_payload_row: dict[str, Any] = {
            **shared_payload,
            "tender_id": tender_id,
            "load_id": order_number,
            "tender_row_index": row_index,
        }
        set_tender(
            workflow_payload_row,
            tender_from_ingest_row(tender_row, order_number=order_number),
        )
        if data_import_id:
            workflow_payload_row["data_import_id"] = data_import_id

        execution_ids.append(
            enqueue_load_tendering_workflow(
                graph_slug=graph_slug,
                payload=workflow_payload_row,
                event_type="tender_created",
            )
        )

    result: dict[str, Any] = {
        "message": "success",
        "execution_ids": execution_ids,
        "event_type": "tender_created",
        "data_import_id": data_import_id,
    }
    logger.info(
        "load_tendering ingest complete data_import_id=%s execution_count=%s",
        data_import_id,
        len(execution_ids),
    )
    return result
