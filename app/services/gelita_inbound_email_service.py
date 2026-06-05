"""Gelita Unipile ingress: L2 domain events for ``load_tendering``."""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.domain.status_parsing import status_type_from_db
from app.models.status import StatusType
from app.services.communications.service import CommunicationsService
from app.domain.delivery_locations_import import (
    unipile_delivery_locations_attachment,
    unipile_first_load_tender_xlsx_attachment,
)
from app.services.email_webhook_ingest_enqueue import (
    enqueue_delivery_locations_import,
    enqueue_load_tendering_tender_created_ingest,
)
from app.services.load_tendering_email_ingest_service import (
    WORKFLOW_NAME,
    enqueue_load_tendering_workflow,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.gelita.order_number import extract_order_number

logger = get_logger(__name__)


class GelitaCarrierEmailIngressError(Exception):
    """``carrier_email_received`` preconditions failed (lifecycle must exist from ``tender_created``)."""


def _has_delivery_locations_attachment(payload: dict[str, Any]) -> bool:
    if not payload.get("has_attachments"):
        return False
    if not isinstance(payload.get("attachments"), list):
        return False
    return unipile_delivery_locations_attachment(payload) is not None


def _has_load_tender_xlsx_attachment(payload: dict[str, Any]) -> bool:
    if not payload.get("has_attachments"):
        return False
    if not isinstance(payload.get("attachments"), list):
        return False
    return unipile_first_load_tender_xlsx_attachment(payload) is not None


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
    3. ``carrier_email_received`` — ``role`` inbox + body ``Order #`` → tender → lifecycle by ``tender_id``
    """

    def __init__(self) -> None:
        self._lifecycle = WorkflowLifecycleService()
        self._tender_service = TenderService()
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
        communication_id = self._communications.record_or_resolve_inbound(
            tenant.tenant_uuid,
            payload,
        )
        # 1. reply email handling
        if _has_in_reply_to(payload):
            ack_response = self._try_ack_received(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
                communication_id=communication_id,
            )
            if ack_response is not None:
                return ack_response

        # 2. new email handling
        has_dl = _has_delivery_locations_attachment(payload)
        has_tender_xlsx = _has_load_tender_xlsx_attachment(payload)

        if has_dl:
            dl_response = self._enqueue_delivery_locations_import(
                payload=payload,
                tenant=tenant,
            )
            if not has_tender_xlsx:
                return dl_response

        if has_tender_xlsx:
            return self._enqueue_tender_created_ingest(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
            )

        # 2.2 carrier_email_received handling
        try:
            return self._carrier_email_received(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
            )
        except GelitaCarrierEmailIngressError as exc:
            logger.warning(
                "gelita carrier_email_received skipped tenant=%s reason=%s",
                tenant.tenant_uuid,
                exc,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "message": "skipped",
                    "event_type": "carrier_email_received",
                    "reason": str(exc),
                },
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

    def _enqueue_delivery_locations_import(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
    ) -> JSONResponse:
        task_id, queue_status = enqueue_delivery_locations_import(
            payload=payload,
            tenant_uuid=tenant.tenant_uuid,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "accepted",
                "event_type": "delivery_locations_updated",
                "task_id": task_id,
                "status": queue_status,
            },
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
        communication_id: str | None = None,
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
        if communication_id:
            workflow_payload["communication_id"] = communication_id

        execution_id = self._enqueue(
            graph_slug=graph_slug,
            payload=workflow_payload,
            event_type="ack_received",
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id, "event_type": "ack_received"},
        )

    def _carrier_email_received(
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

        order_number, thread_id, lifecycle_id, tender_id, lifecycle_row = (
            self._find_lifecycle_row_by_order_number(
                payload=payload,
                tenant_id=tenant.tenant_uuid,
            )
        )

        existing_thread = str(lifecycle_row.get("email_thread_id") or "").strip()
        if existing_thread:
            if existing_thread == thread_id:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={"message": "carrier thread already linked; no enqueue"},
                )
            raise GelitaCarrierEmailIngressError(
                f"lifecycle {lifecycle_id} email_thread_id conflict: "
                f"existing={existing_thread!r} incoming={thread_id!r}"
            )

        self._lifecycle.set_email_thread_id(
            lifecycle_id=lifecycle_id,
            thread_id=thread_id,
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

    def _find_lifecycle_row_by_order_number(
        self,
        *,
        payload: dict[str, Any],
        tenant_id: str,
    ) -> tuple[str, str, str, str, dict[str, Any]]:
        """
        Parse carrier email and load the existing ``load_tendering`` lifecycle.

        Resolves ``tenders`` by order number, then lifecycle by ``tender_id``. Raises
        ``GelitaCarrierEmailIngressError`` if tender or lifecycle from ``tender_created`` is missing.
        Returns ``(order_number, thread_id, lifecycle_id, tender_id, lifecycle_row)``.
        """
        body_html = str(payload.get("body") or "")
        order_number = extract_order_number(body_html)
        if not order_number:
            raise GelitaCarrierEmailIngressError("no order number in carrier email body")

        thread_id = _clean_thread_id(payload)
        if not thread_id:
            raise GelitaCarrierEmailIngressError("missing thread_id on carrier email")

        tender_row = self._tender_service.find_tender_by_order_number(
            tenant_id=tenant_id,
            order_number=order_number,
        )
        if not tender_row:
            raise GelitaCarrierEmailIngressError(
                f"no tender for order_number={order_number!r} (expected from tender_created ingest)"
            )

        tender_id = str(tender_row.get("id") or "").strip()
        # buisness error
        if not tender_id:
            raise GelitaCarrierEmailIngressError(
                f"tender row missing id for order_number={order_number!r}"
            )

        lifecycle_row = self._lifecycle.find_lifecycle_row_by_tender_id(
            tenant_id=tenant_id,
            workflow_name=WORKFLOW_NAME,
            tender_id=tender_id,
        )
        if not lifecycle_row:
            raise GelitaCarrierEmailIngressError(
                f"no load_tendering lifecycle for tender_id={tender_id!r} "
                f"order_number={order_number!r} (expected from tender_created)"
            )

        lifecycle_id = str(lifecycle_row.get("id") or "").strip()
        if not lifecycle_id:
            raise GelitaCarrierEmailIngressError(
                f"lifecycle row missing id for tender_id={tender_id!r} "
                f"order_number={order_number!r}"
            )

        return order_number, thread_id, lifecycle_id, tender_id, lifecycle_row
