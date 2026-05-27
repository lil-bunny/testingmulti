"""Gelita Unipile ingress: L2 domain events for ``load_tendering``."""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.domain.status_parsing import status_type_from_db
from app.models.status import StatusType
from app.services.communications.service import CommunicationsService
from app.services.email_webhook_ingest_enqueue import (
    enqueue_load_tendering_tender_created_ingest,
)
from app.services.load_tendering_email_ingest_service import (
    WORKFLOW_NAME,
    enqueue_load_tendering_workflow,
)
from app.services.tender_service import TenderService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_classifier_service import unipile_first_attachment_by_extension
from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.gelita.order_number import extract_order_number

logger = get_logger(__name__)


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


def _is_inbox_role(payload: dict[str, Any]) -> bool:
    """Unipile ``role`` for inbound mail on the connected account (not drafts/sent)."""
    return str(payload.get("role") or "").strip().lower() == "inbox"


class GelitaInboundEmailService:
    """
    L2 routing for Gelita on a single ``webhook_name``:

    1. ``ack_received`` — lifecycle on ``thread_id`` + ``in_reply_to``
    2. ``tender_created`` — ``.xlsx`` attachment → ingest → per-row enqueue
    3. ``carrier_email_received`` — ``role`` inbox + body ``Order #`` → tender → lifecycle
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
            return self._enqueue_tender_created_ingest(
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
        return enqueue_load_tendering_workflow(
            graph_slug=graph_slug,
            payload=payload,
            event_type=event_type,
        )

    def _enqueue_tender_created_ingest(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
    ) -> JSONResponse:
        task_id, queue_status = enqueue_load_tendering_tender_created_ingest(
            payload=payload,
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            graph_slug=graph_slug,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "accepted",
                "event_type": "tender_created",
                "task_id": task_id,
                "status": queue_status,
            },
        )

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

        lifecycle_id = lifecycle["lifecycle_id"]
        lifecycle_row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        if status_type_from_db(lifecycle_row.get("status")) == StatusType.COMPLETED:
            logger.info(
                "gelita ack_received skipped: lifecycle already completed "
                "lifecycle_id=%s thread_id=%s",
                lifecycle_id,
                thread_id,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "message": "lifecycle completed; ack not processed",
                    "event_type": "ack_received",
                    "workflow_lifecycle_id": lifecycle_id,
                },
            )

        tender_id = lifecycle.get("tender_id") or lifecycle_row.get("tender_id") or ""

        workflow_payload: dict[str, Any] = {
            **payload,
            "thread_id": thread_id,
            "workflow_lifecycle_id": lifecycle_id,
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

    def _try_carrier_email_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
    ) -> JSONResponse:
        if not _is_inbox_role(payload):
            logger.info(
                "gelita carrier: skipping non-inbox webhook role=%r folders=%r",
                payload.get("role"),
                payload.get("folders"),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "non-inbox email; carrier workflow not queued"},
            )

        body_html = str(payload.get("body") or "")
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
