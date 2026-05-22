"""Gelita Unipile ingress: L2 domain events for ``load_tendering``."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import status
from fastapi.responses import JSONResponse

from app.configs.load_tendering_import_projection import LOAD_TENDERING_ROW_PROJECTION
from app.core.logger import get_logger
from app.services.email_import_projection import (
    load_email_data_import_projection,
    persist_tender_rows_from_email_import_projection,
)
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.communications.service import CommunicationsService
from app.services.tender_service import TenderService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_classifier_service import unipile_first_attachment_by_extension
from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async
from app.tools.gelita.email_parser import extract_order_number

logger = get_logger(__name__)

WORKFLOW_NAME = "load_tendering"


def _load_tendering_row_correlation_load_id(
    data_import_id: Optional[str],
    row_index: int,
    tender_row: dict[str, Any],
) -> str:
    did = str(data_import_id or "").strip() or "no-import"
    order = str(tender_row.get("order_number") or "").strip() or "no-order"
    return f"{did}:{row_index}:{order}"


def _has_xlsx_attachment(payload: dict[str, Any]) -> bool:
    if not payload.get("has_attachments"):
        return False
    if not isinstance(payload.get("attachments"), list):
        return False
    return unipile_first_attachment_by_extension(payload, "xlsx") is not None


def _has_in_reply_to(payload: dict[str, Any]) -> bool:
    val = payload.get("in_reply_to")
    if val is None:
        return False
    return bool(str(val).strip())


def _clean_thread_id(payload: dict[str, Any]) -> str | None:
    raw = payload.get("thread_id")
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


class GelitaInboundEmailService:
    """
    L2 routing for Gelita on a single ``webhook_name``:

    1. ``ack_received`` — lifecycle on ``thread_id`` + ``in_reply_to``
    2. ``tender_created`` — ``.xlsx`` attachment → ingest → per-row enqueue
    3. ``carrier_email_received`` — body ``Order #`` → tender → lifecycle
    """

    def __init__(self) -> None:
        self._lifecycle = WorkflowLifecycleService()
        self._tenders = TenderService()
        self._communications = CommunicationsService()

    async def handle(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
    ) -> JSONResponse:
        graph_slug = resolve_workflow_graph_tenant_id(
            data_import_tenant_id=tenant.tenant_uuid,
            webhook_name=str(payload.get("webhook_name") or ""),
        )
        # store the inbound email in the communications table
        self._communications.record_inbound(tenant.tenant_uuid, payload)
        # 1. reply email handling
        if _has_in_reply_to(payload):
            ack_response = self._try_ack_received(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
            )
            if ack_response is not None:
                return ack_response

        # 2. new email handling
        # 2.1 tender_created handling
        if _has_xlsx_attachment(payload):
            return await self._handle_tender_created(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
            )
        # 2.2 carrier_email_received handling
        return self._try_carrier_email_received(
            payload=payload,
            tenant=tenant,
            graph_slug=graph_slug,
        )

    def _enqueue(
        self,
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
            "gelita unipile queued task_id=%s execution_id=%s event_type=%s",
            task.id,
            execution_id,
            event_type,
        )
        return execution_id

    def _try_ack_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
    ) -> JSONResponse | None:
        thread_id = _clean_thread_id(payload)
        if not thread_id:
            return None

        lifecycle = self._lifecycle.read_lifecycle(
            tenant_id=tenant.tenant_uuid,
            workflow_name=WORKFLOW_NAME,
            thread_id=thread_id,
        )
        if not lifecycle.get("found"):
            return None

        tender_id = lifecycle.get("tender_id") or ""
        if not tender_id:
            row = self._lifecycle.read_lifecycle_row_by_id(lifecycle["lifecycle_id"])
            tender_id = (row or {}).get("tender_id") or ""

        workflow_payload: dict[str, Any] = {
            **payload,
            "thread_id": thread_id,
            "workflow_lifecycle_id": lifecycle["lifecycle_id"],
        }
        if tender_id:
            workflow_payload["tender_id"] = tender_id

        execution_id = self._enqueue(
            graph_slug=graph_slug,
            payload=workflow_payload,
            event_type="ack_received",
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id, "event_type": "ack_received"},
        )

    async def _handle_tender_created(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
    ) -> JSONResponse:
        data_import_id = await process_email_webhook_attachment_import(
            payload=payload,
            workflow_name=WORKFLOW_NAME,
            data_import_tenant_id=tenant.tenant_uuid,
            data_import_data_type="load_tender",
        )

        projected_rows = load_email_data_import_projection(
            tenant_id=tenant.tenant_uuid,
            data_import_id=data_import_id,
            projection=LOAD_TENDERING_ROW_PROJECTION,
        )
        tender_ids_by_row = persist_tender_rows_from_email_import_projection(
            tenant_id=tenant.tenant_uuid,
            data_import_id=data_import_id,
            projected_rows=projected_rows,
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
                    "gelita tender_created: skip row (new tender not created) row_index=%s "
                    "order_number=%r",
                    row_index,
                    tender_row.get("order_number"),
                )
                continue
            if tender_id in enqueued_tender_ids:
                logger.info(
                    "gelita tender_created: skip duplicate order row row_index=%s tender_id=%s",
                    row_index,
                    tender_id,
                )
                continue
            enqueued_tender_ids.add(tender_id)

            workflow_payload_row: dict[str, Any] = {
                **shared_payload,
                "tender_id": tender_id,
                "load_id": _load_tendering_row_correlation_load_id(
                    data_import_id, row_index, tender_row
                ),
                "tender_row": tender_row,
                "tender_row_index": row_index,
            }
            if data_import_id:
                workflow_payload_row["data_import_id"] = data_import_id

            execution_ids.append(
                self._enqueue(
                    graph_slug=graph_slug,
                    payload=workflow_payload_row,
                    event_type="tender_created",
                )
            )

        body: dict[str, Any] = {
            "message": "success",
            "execution_ids": execution_ids,
            "event_type": "tender_created",
        }
        if data_import_id:
            body["data_import_id"] = data_import_id
        return JSONResponse(status_code=status.HTTP_200_OK, content=body)

    def _try_carrier_email_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
    ) -> JSONResponse:
        body_html = str(payload.get("body") or payload.get("body_plain") or "")
        order_number = extract_order_number(body_html)
        if not order_number:
            logger.warning("gelita carrier: no order number in email body")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "no order number; workflow not queued"},
            )

        tender_row = self._tenders.find_by_order_number(
            tenant_id=tenant.tenant_uuid,
            order_number=order_number,
        )
        if not tender_row:
            logger.warning(
                "gelita carrier: no tender for order_number=%r tenant=%s",
                order_number,
                tenant.tenant_uuid,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "tender not found; workflow not queued"},
            )

        tender_id = tender_row["id"]
        lifecycle_check = self._lifecycle.check_lifecycle_exists(
            tenant_id=tenant.tenant_uuid,
            workflow_name=WORKFLOW_NAME,
            tender_id=tender_id,
        )
        if not lifecycle_check.get("exists"):
            logger.warning(
                "gelita carrier: no lifecycle for tender_id=%s order_number=%r",
                tender_id,
                order_number,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "lifecycle not found; workflow not queued"},
            )

        lifecycle_id = str(lifecycle_check["lifecycle_id"])
        thread_id = _clean_thread_id(payload)
        if not thread_id:
            logger.warning("gelita carrier: missing thread_id")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "missing thread_id; workflow not queued"},
            )

        lifecycle_row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        existing_thread = str(lifecycle_row.get("email_thread_id") or "").strip()
        if existing_thread:
            if existing_thread == thread_id:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={"message": "carrier thread already linked; no enqueue"},
                )
            logger.warning(
                "gelita carrier: lifecycle %s already has email_thread_id=%r",
                lifecycle_id,
                existing_thread,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "lifecycle thread conflict; workflow not queued"},
            )

        self._lifecycle.update_lifecycle_keys(
            lifecycle_id=lifecycle_id,
            thread_id=thread_id,
            # tender_id=tender_id,
        )

        workflow_payload: dict[str, Any] = {
            **payload,
            "tender_id": tender_id,
            "order_number": order_number,
            "thread_id": thread_id,
            "workflow_lifecycle_id": lifecycle_id,
        }
        execution_id = self._enqueue(
            graph_slug=graph_slug,
            payload=workflow_payload,
            event_type="carrier_email_received",
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "success",
                "execution_id": execution_id,
                "event_type": "carrier_email_received",
            },
        )
