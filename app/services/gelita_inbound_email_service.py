"""Gelita Unipile ingress: L2 domain events for ``load_tendering``."""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.domain.status_parsing import status_type_from_db
from app.models.status import StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.domain.delivery_locations_import import unipile_delivery_locations_attachment
from app.domain.load_tendering_import import email_load_tender_xlsx_attachment
from app.services.email_webhook_ingest_enqueue import (
    enqueue_delivery_locations_import,
    enqueue_load_tendering_tender_created_ingest,
)
from app.services.load_tendering_email_ingest_service import (
    WORKFLOW_NAME,
    enqueue_gelita_load_tendering_and_link,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.domain.gelita.routing_guide_lifecycle import (
    routing_guide_attempt_from_metadata,
    routing_guide_order_matches_lifecycle,
    routing_guide_same_attempt_thread_conflict,
)
from app.domain.load_tendering_settings import is_ftl_load_type
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
    return email_load_tender_xlsx_attachment(payload) is not None


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


def _ingress_skip_response(
    *,
    event_type: str,
    lifecycle_id: str,
    message: str = "skipped",
    reason: str | None = None,
) -> JSONResponse:
    """Standard 200 skip body for Gelita load_tendering ingress paths."""
    content: dict[str, Any] = {
        "message": message,
        "event_type": event_type,
        "workflow_lifecycle_id": lifecycle_id,
    }
    if reason is not None:
        content["reason"] = reason
    return JSONResponse(status_code=status.HTTP_200_OK, content=content)


def _ingress_comm_linked_response(
    *,
    event_type: str,
    lifecycle_id: str,
) -> JSONResponse:
    """200 when inbound comm was already linked to a workflow run (Celery retry guard)."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "message": "communication already linked; no enqueue",
            "event_type": event_type,
            "workflow_lifecycle_id": lifecycle_id,
        },
    )


class GelitaInboundEmailService:
    """
    L2 routing for Gelita after recipient-based L1 tenant resolution:

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
            tenant_slug_hint=tenant.tenant_slug,
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
                communication_id=communication_id,
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

    def _resolve_tender_load_type(
        self,
        *,
        tenant_id: str,
        order_number: str | None,
        tender_id: str | None,
    ) -> str | None:
        """Resolve load type from order lookup or tender id; used by FTL ingress guards."""
        if order_number:
            tender_row = self._tender_service.find_tender_by_order_number(
                tenant_id=tenant_id,
                order_number=order_number,
            )
            if tender_row:
                load_type = tender_row.get("load_type")
                if load_type is not None and str(load_type).strip():
                    return str(load_type).strip()
        tid = str(tender_id or "").strip()
        if tid:
            bundle = self._tender_service.read_order(tenant_id=tenant_id, tender_id=tid)
            if bundle and isinstance(bundle.get("tender"), dict):
                return bundle["tender"].get("load_type")
        return None

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

        lifecycle_id = self._communications.resolve_lifecycle_id_for_thread(
            tenant_id=tenant.tenant_uuid,
            thread_id=thread_id,
            workflow_name=WORKFLOW_NAME,
        )
        if not lifecycle_id:
            return None
        lifecycle_row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        if status_type_from_db(lifecycle_row.get("status")) == StatusType.COMPLETED:
            logger.info(
                "gelita ack_received skipped: lifecycle already completed "
                "lifecycle_id=%s thread_id=%s",
                lifecycle_id,
                thread_id,
            )
            return _ingress_skip_response(
                event_type="ack_received",
                lifecycle_id=lifecycle_id,
                message="lifecycle completed; ack not processed",
            )

        lifecycle_tender_id = str(lifecycle_row.get("tender_id") or "").strip()
        body_html = str(payload.get("body") or "")
        order_number = extract_order_number(body_html)
        if order_number:
            tender_row = self._tender_service.find_tender_by_order_number(
                tenant_id=tenant.tenant_uuid,
                order_number=order_number,
            )
            resolved_tender_id = str((tender_row or {}).get("id") or "").strip()
            if resolved_tender_id and not routing_guide_order_matches_lifecycle(
                resolved_tender_id,
                lifecycle_tender_id,
            ):
                logger.info(
                    "gelita ack_received skipped: stale order rollover "
                    "lifecycle_id=%s lifecycle_tender_id=%s resolved_tender_id=%s",
                    lifecycle_id,
                    lifecycle_tender_id,
                    resolved_tender_id,
                )
                return _ingress_skip_response(
                    event_type="ack_received",
                    lifecycle_id=lifecycle_id,
                    reason="stale_order_rollover",
                )

        lifecycle_meta = lifecycle_row.get("metadata")
        live_attempt = routing_guide_attempt_from_metadata(lifecycle_meta)
        load_type = self._resolve_tender_load_type(
            tenant_id=tenant.tenant_uuid,
            order_number=order_number,
            tender_id=lifecycle_tender_id,
        )
        if is_ftl_load_type(load_type):
            if self._communications.is_retired_carrier_thread(
                tenant_id=tenant.tenant_uuid,
                thread_id=thread_id,
                workflow_lifecycle_id=lifecycle_id,
                live_attempt=live_attempt,
            ):
                logger.info(
                    "gelita ack_received skipped: retired carrier thread "
                    "lifecycle_id=%s thread_id=%s live_attempt=%s",
                    lifecycle_id,
                    thread_id,
                    live_attempt,
                )
                return _ingress_skip_response(
                    event_type="ack_received",
                    lifecycle_id=lifecycle_id,
                    reason="retired_carrier_thread",
                )

        tender_id = lifecycle_tender_id
        is_ftl = is_ftl_load_type(load_type)

        workflow_payload: dict[str, Any] = {
            **payload,
            "thread_id": thread_id,
            "workflow_lifecycle_id": lifecycle_id,
        }
        if tender_id:
            workflow_payload["tender_id"] = tender_id
        if communication_id:
            workflow_payload["communication_id"] = communication_id
        # FTL reject path never hits read_tender_row; seed attempt so routing_guide_router
        # can choose exhausted vs advance (mirrors carrier_email_received).
        if is_ftl:
            workflow_payload["routing_guide_attempt"] = live_attempt

        linked = self._skip_if_communication_linked(
            communication_id=communication_id,
            event_type="ack_received",
            lifecycle_id=lifecycle_id,
            log_label="gelita ack_received",
        )
        if linked is not None:
            return linked

        execution_id = enqueue_gelita_load_tendering_and_link(
            graph_slug=graph_slug,
            tenant_uuid=tenant.tenant_uuid,
            workflow_lifecycle_id=lifecycle_id,
            payload=workflow_payload,
            event_type=WorkflowRunEventType.ACK_RECEIVED,
            communication_id=communication_id,
            thread_id=thread_id,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id, "event_type": "ack_received"},
        )

    def _skip_if_communication_linked(
        self,
        *,
        communication_id: str | None,
        event_type: str,
        lifecycle_id: str,
        log_label: str,
    ) -> JSONResponse | None:
        """Return skip response when inbound comm is already linked to a workflow run."""
        if not communication_id:
            return None
        if not self._communications.is_communication_linked_to_run(
            communication_id=communication_id,
        ):
            return None
        logger.info(
            "%s skipped: communication already linked comm_id=%s lifecycle_id=%s",
            log_label,
            communication_id,
            lifecycle_id,
        )
        return _ingress_comm_linked_response(
            event_type=event_type,
            lifecycle_id=lifecycle_id,
        )

    def _check_carrier_thread_ingress(
        self,
        *,
        tenant_id: str,
        lifecycle_id: str,
        thread_id: str,
        routing_guide_attempt: int | None,
    ) -> JSONResponse | None:
        """
        Idempotent skip or conflict check before carrier enqueue.

        ``routing_guide_attempt`` scopes FTL lookups; ``None`` keeps LTL global thread logic.
        """
        if self._communications.is_thread_linked_to_lifecycle(
            tenant_id=tenant_id,
            thread_id=thread_id,
            workflow_lifecycle_id=lifecycle_id,
            routing_guide_attempt=routing_guide_attempt,
        ):
            content: dict[str, Any] = {
                "message": "carrier thread already linked; no enqueue",
            }
            if routing_guide_attempt is not None:
                content["event_type"] = "carrier_email_received"
            return JSONResponse(status_code=status.HTTP_200_OK, content=content)

        linked_thread = self._communications.find_linked_thread_for_lifecycle(
            tenant_id=tenant_id,
            workflow_lifecycle_id=lifecycle_id,
            routing_guide_attempt=routing_guide_attempt,
        )
        if routing_guide_same_attempt_thread_conflict(
            linked_thread=linked_thread,
            incoming_thread=thread_id,
        ):
            raise GelitaCarrierEmailIngressError(
                f"lifecycle {lifecycle_id} carrier thread conflict: "
                f"existing={linked_thread!r} incoming={thread_id!r}"
            )
        return None

    def _carrier_email_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
        communication_id: str | None = None,
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

        order_number, thread_id, lifecycle_id, tender_id, lifecycle_row, tender_row = (
            self._find_lifecycle_row_by_order_number(
                payload=payload,
                tenant_id=tenant.tenant_uuid,
            )
        )

        if status_type_from_db(lifecycle_row.get("status")) == StatusType.COMPLETED:
            logger.info(
                "gelita carrier_email_received skipped: lifecycle completed "
                "lifecycle_id=%s thread_id=%s",
                lifecycle_id,
                thread_id,
            )
            return _ingress_skip_response(
                event_type="carrier_email_received",
                lifecycle_id=lifecycle_id,
                reason="lifecycle_completed",
            )

        lifecycle_tender_id = str(lifecycle_row.get("tender_id") or tender_id or "").strip()
        if not routing_guide_order_matches_lifecycle(tender_id, lifecycle_tender_id):
            logger.info(
                "gelita carrier_email_received skipped: stale order rollover "
                "lifecycle_id=%s lifecycle_tender_id=%s resolved_tender_id=%s",
                lifecycle_id,
                lifecycle_tender_id,
                tender_id,
            )
            return _ingress_skip_response(
                event_type="carrier_email_received",
                lifecycle_id=lifecycle_id,
                reason="stale_order_rollover",
            )

        lifecycle_meta = lifecycle_row.get("metadata")
        live_attempt = routing_guide_attempt_from_metadata(lifecycle_meta)
        load_type = tender_row.get("load_type") or self._resolve_tender_load_type(
            tenant_id=tenant.tenant_uuid,
            order_number=order_number,
            tender_id=tender_id,
        )
        is_ftl = is_ftl_load_type(load_type)
        attempt_kwarg = live_attempt if is_ftl else None

        skip = self._check_carrier_thread_ingress(
            tenant_id=tenant.tenant_uuid,
            lifecycle_id=lifecycle_id,
            thread_id=thread_id,
            routing_guide_attempt=attempt_kwarg,
        )
        if skip is not None:
            return skip

        linked = self._skip_if_communication_linked(
            communication_id=communication_id,
            event_type="carrier_email_received",
            lifecycle_id=lifecycle_id,
            log_label="gelita carrier_email_received",
        )
        if linked is not None:
            return linked

        workflow_payload: dict[str, Any] = {
            **payload,
            "tender_id": tender_id,
            "order_number": order_number,
            "thread_id": thread_id,
            "workflow_lifecycle_id": lifecycle_id,
        }
        if is_ftl:
            workflow_payload["routing_guide_attempt"] = live_attempt
        if communication_id:
            workflow_payload["communication_id"] = communication_id

        execution_id = enqueue_gelita_load_tendering_and_link(
            graph_slug=graph_slug,
            tenant_uuid=tenant.tenant_uuid,
            workflow_lifecycle_id=lifecycle_id,
            payload=workflow_payload,
            event_type="carrier_email_received",
            communication_id=communication_id,
            thread_id=thread_id,
            routing_guide_attempt=live_attempt if is_ftl else None,
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
    ) -> tuple[str, str, str, str, dict[str, Any], dict[str, Any]]:
        """
        Parse carrier email and load the ``load_tendering`` lifecycle for the order.

        Resolves the latest tender for the order number, then lifecycle by ``tender_id``.
        Raises ``GelitaCarrierEmailIngressError`` when tender or lifecycle is missing.
        Returns ``(order_number, thread_id, lifecycle_id, tender_id, lifecycle_row, tender_row)``.
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

        return order_number, thread_id, lifecycle_id, tender_id, lifecycle_row, tender_row
