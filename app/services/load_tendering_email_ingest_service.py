"""Background ingest: email xlsx → data_imports → tenders → load_tendering workflows."""

from __future__ import annotations

import uuid
from typing import Any

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
    process_email_webhook_attachment_import_for_attachment,
)
from app.services.communications.service import CommunicationsService
from app.services.workflow_runs_service import WorkflowRunsService

logger = get_logger(__name__)

WORKFLOW_NAME = "load_tendering"


def enqueue_load_tendering_workflow(
    *,
    graph_slug: str,
    payload: dict[str, Any],
    event_type: str,
) -> str:
    """
    Serialize-enqueue one ``load_tendering`` graph start.

    Returns the new ``execution_id`` (caller may still treat buffered starts as
    accepted work on the lifecycle run queue).
    """
    from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService

    execution_id = str(uuid.uuid4())
    body = {**payload, "event_type": event_type, "execution_id": execution_id}
    tenant_id = str(body.get("tenant_id") or graph_slug).strip()
    lifecycle_run_serializer_service = LifecycleRunSerializerService()
    result = lifecycle_run_serializer_service.resolve_then_enqueue(
        tenant_id=tenant_id,
        tenant_slug=graph_slug,
        workflow_name=WORKFLOW_NAME,
        payload=body,
    )
    logger.info(
        "load_tendering serialize status=%s celery_task_id=%s execution_id=%s "
        "event_type=%s lifecycle_id=%s",
        result.status,
        result.celery_task_id,
        execution_id,
        event_type,
        result.lifecycle_id,
    )
    return execution_id


def enqueue_gelita_load_tendering_and_link(
    *,
    graph_slug: str,
    tenant_uuid: str,
    workflow_lifecycle_id: str,
    payload: dict[str, Any],
    event_type: str,
    communication_id: str | None = None,
    thread_id: str | None = None,
    routing_guide_attempt: int | None = None,
) -> str:
    """
    Enqueue ``load_tendering``, record ``workflow_runs`` synchronously, and patch comms.

    Recording the run before HTTP 200 lets ack ingress resolve thread → lifecycle via
    prior patched rows on the same Unipile thread.
    """
    execution_id = enqueue_load_tendering_workflow(
        graph_slug=graph_slug,
        payload={
            **payload,
            "tenant_id": tenant_uuid,
            "workflow_lifecycle_id": workflow_lifecycle_id,
        },
        event_type=event_type,
    )

    workflow_runs_service = WorkflowRunsService()
    workflow_runs_service.record_workflow_run(
        run_id=execution_id,
        tenant_id=tenant_uuid,
        event_type=event_type,
        workflow_lifecycle_id=workflow_lifecycle_id,
    )

    communications_service = CommunicationsService()
    if communication_id and event_type == "carrier_email_received":
        communications_service.link_carrier_email_received_communication(
            communication_id=communication_id,
            workflow_run_id=execution_id,
            workflow_lifecycle_id=workflow_lifecycle_id,
        )
    elif communication_id:
        communications_service.link_inbound_to_workflow_run(
            communication_id=communication_id,
            workflow_run_id=execution_id,
            workflow_lifecycle_id=workflow_lifecycle_id,
        )
    if thread_id:
        communications_service.link_workflow_run_to_thread(
            tenant_id=tenant_uuid,
            thread_id=thread_id,
            workflow_run_id=execution_id,
            workflow_lifecycle_id=workflow_lifecycle_id,
        )

    return execution_id


async def process_tender_created_from_email_webhook(
    *,
    payload: dict[str, Any],
    tenant_uuid: str,
    tenant_slug: str,
    graph_slug: str,
    attachment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full tender_created pipeline (attachment → DB → per-row workflow enqueue).

    When ``attachment`` is provided (Gelita ingress after classification), skips
    re-scanning ``payload["attachments"]`` for ``customers_orders_*.xlsx``.
    """
    attachment_import_kwargs = {
        "payload": payload,
        "workflow_name": WORKFLOW_NAME,
        "data_import_tenant_id": tenant_uuid,
        "data_import_data_type": DataImportDataType.LOAD_TENDER,
        "ingest_source_type": DataImportSourceType.EMAIL,
        "skip_fetch_if_existing": True,
    }
    if attachment is not None:
        data_import_id = await process_email_webhook_attachment_import_for_attachment(
            attachment=attachment,
            **attachment_import_kwargs,
        )
    else:
        data_import_id = await process_email_webhook_attachment_import(
            **attachment_import_kwargs
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
            "order_number": order_number,
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
