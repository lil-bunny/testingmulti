"""Gelita Unipile ingress: L2 domain events for ``load_tendering``."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.status_parsing import status_type_from_db
from app.models.status import StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.domain.gelita.email_attachments import classify_gelita_email_xlsx_attachments
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import_for_attachment,
)
from app.services.load_tendering_email_ingest_service import (
    WORKFLOW_NAME,
    enqueue_gelita_load_tendering_and_link,
    process_tender_created_from_email_webhook,
)
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

if TYPE_CHECKING:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

logger = get_logger(__name__)


class GelitaCarrierEmailIngressError(Exception):
    """``carrier_email_received`` preconditions failed (lifecycle must exist from ``tender_created``)."""


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


def _ingress_skip_result(
    *,
    event_type: str,
    reason: str,
) -> IngressResult:
    return IngressResult(outcome="skipped", event_type=event_type, reason=reason)


class GelitaEmailIngressService:
    """
    Gelita L2 ingress for ``load_tendering`` (runs in the Celery ingress worker).

    Event order in production: ``tender_created`` → ``carrier_email_received`` → ``ack_received``.
    Out-of-order mail is skipped (no retry). ``process()`` branches on payload shape, not tenant config.
    """

    def __init__(self) -> None:
        self._lifecycle = WorkflowLifecycleService()
        self._tender_service = TenderService()
        self._communications = CommunicationsService()

    async def process(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None,
    ) -> IngressResult:
        """
        Classify one inbound Gelita email and run guards before workflow enqueue.

        Branch order: reply/ack → delivery-locations xlsx → tender xlsx ingest → carrier inbox mail.
        Communication is already recorded by ``process_inbound_unipile_email``; this method only routes.
        """
        graph_slug = resolve_workflow_graph_tenant_id(
            data_import_tenant_id=tenant.tenant_uuid,
            tenant_slug_hint=tenant.tenant_slug,
        )

        # 1. Thread replies (in_reply_to) — ack_received on an existing load_tendering lifecycle.
        if _has_in_reply_to(payload):
            ack_result = self._try_ack_received(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
                communication_id=communication_id,
            )
            if ack_result is not None:
                return ack_result

        classified_attachments = classify_gelita_email_xlsx_attachments(payload)
        delivery_locations_attachment = (
            classified_attachments.delivery_locations_attachment
        )
        load_tendering_xlsx_attachment = (
            classified_attachments.load_tendering_xlsx_attachment
        )

        # 2. delivery_location.xlsx — upsert reference data (may coexist with tender xlsx on same mail).
        if delivery_locations_attachment is not None:
            delivery_locations_result = await self._process_delivery_locations_import(
                payload=payload,
                tenant=tenant,
                attachment=delivery_locations_attachment,
            )
            if load_tendering_xlsx_attachment is None:
                return delivery_locations_result

        # 3. customers_orders_loads.xlsx — ingest rows and enqueue one workflow per new tender.
        if load_tendering_xlsx_attachment is not None:
            return await self._process_tender_created_ingest(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
                attachment=load_tendering_xlsx_attachment,
            )

        # 4. Carrier reply on inbox — Order # in body links to tender_created lifecycle.
        try:
            return self._carrier_email_received(
                payload=payload,
                tenant=tenant,
                graph_slug=graph_slug,
                communication_id=communication_id,
            )
        except GelitaCarrierEmailIngressError as carrier_error:
            logger.warning(
                "gelita carrier_email_received skipped tenant=%s reason=%s",
                tenant.tenant_uuid,
                carrier_error,
            )
            return _ingress_skip_result(
                event_type="carrier_email_received",
                reason=str(carrier_error),
            )

    async def _process_delivery_locations_import(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        attachment: dict[str, Any],
    ) -> IngressResult:
        """Fetch delivery_location.xlsx and persist delivery-location reference import."""
        data_import_id = await process_email_webhook_attachment_import_for_attachment(
            payload=payload,
            attachment=attachment,
            workflow_name=WORKFLOW_NAME,
            data_import_tenant_id=tenant.tenant_uuid,
            data_import_data_type=DataImportDataType.DELIVERY_LOCATION,
            ingest_source_type=DataImportSourceType.EMAIL,
            skip_fetch_if_existing=False,
        )
        if not data_import_id:
            raise RuntimeError(
                "delivery locations ingest: no data_import_id "
                "(missing delivery_location.xlsx or fetch failed)"
            )
        logger.info(
            "delivery locations ingest complete tenant_id=%s data_import_id=%s",
            tenant.tenant_uuid,
            data_import_id,
        )
        return IngressResult(
            outcome="processed",
            event_type="delivery_locations_updated",
        )

    async def _process_tender_created_ingest(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        graph_slug: str,
        attachment: dict[str, Any],
    ) -> IngressResult:
        """
        Ingest tender xlsx inline (formerly a separate Celery handler).

        Creates tenders and enqueues one ``load_tendering`` run per new spreadsheet row.
        """
        result = await process_tender_created_from_email_webhook(
            payload=payload,
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            graph_slug=graph_slug,
            attachment=attachment,
        )
        execution_ids = tuple(str(eid) for eid in (result.get("execution_ids") or []))
        return IngressResult(
            outcome="enqueued",
            event_type="tender_created",
            execution_ids=execution_ids,
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
    ) -> IngressResult | None:
        """
        Match ``ack_received`` when the mail is a thread reply tied to a load_tendering lifecycle.

        Returns ``None`` when the reply is not on a known carrier thread (caller may try other branches).
        Skips when lifecycle is completed, order rolled over, or FTL carrier thread was retired.
        """
        thread_id = _clean_thread_id(payload)
        if not thread_id:
            return None

        # Resolve lifecycle from prior carrier_email_received comm patches on this thread.
        lifecycle_id = self._communications.resolve_lifecycle_id_for_thread(
            tenant_id=tenant.tenant_uuid,
            thread_id=thread_id,
            workflow_name=WORKFLOW_NAME,
        )
        if not lifecycle_id:
            return None
        lifecycle_row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}

        # Guard: lifecycle already accepted — ack is a no-op.
        if status_type_from_db(lifecycle_row.get("status")) == StatusType.COMPLETED:
            logger.info(
                "gelita ack_received skipped: lifecycle already completed "
                "lifecycle_id=%s thread_id=%s",
                lifecycle_id,
                thread_id,
            )
            return _ingress_skip_result(
                event_type="ack_received",
                reason="lifecycle completed; ack not processed",
            )

        lifecycle_tender_id = str(lifecycle_row.get("tender_id") or "").strip()
        body_html = str(payload.get("body") or "")
        order_number = extract_order_number(body_html)

        # Guard: body order number points at a newer tender row (order rollover).
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
                return _ingress_skip_result(
                    event_type="ack_received",
                    reason="stale_order_rollover",
                )

        lifecycle_meta = lifecycle_row.get("metadata")
        live_attempt = routing_guide_attempt_from_metadata(lifecycle_meta)
        load_type = self._resolve_tender_load_type(
            tenant_id=tenant.tenant_uuid,
            order_number=order_number,
            tender_id=lifecycle_tender_id,
        )

        # FTL: skip ack on a carrier thread superseded by a later routing-guide attempt.
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
                return _ingress_skip_result(
                    event_type="ack_received",
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

        # Celery retry / duplicate webhook — comm already linked to a prior run.
        linked = self._skip_if_communication_linked(
            communication_id=communication_id,
            event_type="ack_received",
            log_label="gelita ack_received",
        )
        if linked is not None:
            return linked

        # Record workflow_run + link comm/thread before workflow worker starts (thread → lifecycle lookup).
        execution_id = enqueue_gelita_load_tendering_and_link(
            graph_slug=graph_slug,
            tenant_uuid=tenant.tenant_uuid,
            workflow_lifecycle_id=lifecycle_id,
            payload=workflow_payload,
            event_type=WorkflowRunEventType.ACK_RECEIVED,
            communication_id=communication_id,
            thread_id=thread_id,
        )
        return IngressResult(
            outcome="enqueued",
            event_type="ack_received",
            execution_ids=(execution_id,),
        )

    def _skip_if_communication_linked(
        self,
        *,
        communication_id: str | None,
        event_type: str,
        log_label: str,
    ) -> IngressResult | None:
        """Return skip result when inbound comm is already linked to a workflow run."""
        if not communication_id:
            return None
        if not self._communications.is_communication_linked_to_run(
            communication_id=communication_id,
        ):
            return None
        logger.info(
            "%s skipped: communication already linked comm_id=%s",
            log_label,
            communication_id,
        )
        return _ingress_skip_result(
            event_type=event_type,
            reason="communication already linked",
        )

    def _check_carrier_thread_ingress(
        self,
        *,
        tenant_id: str,
        lifecycle_id: str,
        thread_id: str,
        routing_guide_attempt: int | None,
    ) -> IngressResult | None:
        """
        Idempotent carrier-thread checks before ``carrier_email_received`` enqueue.

        FTL scopes by ``routing_guide_attempt``; LTL uses lifecycle-wide thread linkage.
        Raises when the same attempt already has a different carrier thread.
        """
        if self._communications.is_thread_linked_to_lifecycle(
            tenant_id=tenant_id,
            thread_id=thread_id,
            workflow_lifecycle_id=lifecycle_id,
            routing_guide_attempt=routing_guide_attempt,
        ):
            return _ingress_skip_result(
                event_type="carrier_email_received",
                reason="carrier thread already linked",
            )

        # Same routing-guide attempt must not bind two different Unipile threads.
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
    ) -> IngressResult:
        """
        First carrier reply after ``tender_created`` — binds thread to lifecycle and enqueues workflow.

        Requires inbox role, Order # in body, existing tender + lifecycle from xlsx ingest.
        """
        if not _is_inbox_role(payload):
            logger.info(
                "gelita carrier: skipping non-inbox webhook role=%r folders=%r",
                payload.get("role"),
                payload.get("folders"),
            )
            return IngressResult(
                outcome="no_match",
                reason="non-inbox email; carrier workflow not queued",
            )

        # Body Order # → latest tender row → load_tendering lifecycle (must exist from tender_created).
        order_number, thread_id, lifecycle_id, tender_id, lifecycle_row, tender_row = (
            self._find_lifecycle_row_by_order_number(
                payload=payload,
                tenant_id=tenant.tenant_uuid,
            )
        )

        # Guard: load already accepted — carrier reply is too late in the sequence.
        if status_type_from_db(lifecycle_row.get("status")) == StatusType.COMPLETED:
            logger.info(
                "gelita carrier_email_received skipped: lifecycle completed "
                "lifecycle_id=%s thread_id=%s",
                lifecycle_id,
                thread_id,
            )
            return _ingress_skip_result(
                event_type="carrier_email_received",
                reason="lifecycle_completed",
            )

        lifecycle_tender_id = str(lifecycle_row.get("tender_id") or tender_id or "").strip()
        # Guard: spreadsheet re-import created a newer tender for the same order number.
        if not routing_guide_order_matches_lifecycle(tender_id, lifecycle_tender_id):
            logger.info(
                "gelita carrier_email_received skipped: stale order rollover "
                "lifecycle_id=%s lifecycle_tender_id=%s resolved_tender_id=%s",
                lifecycle_id,
                lifecycle_tender_id,
                tender_id,
            )
            return _ingress_skip_result(
                event_type="carrier_email_received",
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
        # FTL threads are scoped per routing-guide attempt; LTL uses one thread per lifecycle.
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

        # Same pre-enqueue linking as ack — enables later thread → lifecycle resolution.
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
        return IngressResult(
            outcome="enqueued",
            event_type="carrier_email_received",
            execution_ids=(execution_id,),
        )

    def _find_lifecycle_row_by_order_number(
        self,
        *,
        payload: dict[str, Any],
        tenant_id: str,
    ) -> tuple[str, str, str, str, dict[str, Any], dict[str, Any]]:
        """
        Walk carrier mail prerequisites: Order # → tender row → load_tendering lifecycle.

        Raises ``GelitaCarrierEmailIngressError`` when ingest has not created tender/lifecycle yet.
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
