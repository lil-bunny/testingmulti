"""Pre-graph ingress for ``pod_lifecycle`` (route_completed dedupe + email_received correlation).

``email_received`` strict policy: resolve shipment from payload or email thread only
(requires an existing ``shipments`` row, normally created by ratecon). Attachment
filename load-id upsert is not used. A ``ratecon`` workflow_lifecycle must exist before
the graph runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle.guards import (
    is_convoy_from_turvo_shipment_payload,
    is_pod_processing_complete_sub_status,
    pod_email_status_eligible_from_turvo_payload,
)
from app.domain.status_parsing import sub_status_type_from_db
from app.integrations.turvo.documents import check_pod_by_shipment_id
from app.domain.unipile_email_thread import resolve_primary_shipment_from_thread_rows
from app.integrations.turvo.shipments import get_shipment
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService

logger = get_logger(__name__)

POD_LIFECYCLE_WORKFLOW = "pod_lifecycle"
RATECON_GATE_WORKFLOW = "ratecon"
POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS = "invalid_shipment_status"
POD_EMAIL_SKIP_TURVO_FETCH_FAILED = "turvo_shipment_fetch_failed"
POD_EMAIL_SKIP_INVALID_ATTACHMENT = "invalid_attachment"
ROUTE_COMPLETED_SKIP_CONVOY_LOAD = "convoy_load"
ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS = "pod_already_exists"


class PodEmailIngressSkipped(Exception):
    """POD reply email blocked at ingress (return 200 skip to webhook caller)."""

    def __init__(
        self,
        reason: str,
        *,
        shipments_row_id: str | None = None,
    ) -> None:
        self.reason = reason
        self.shipments_row_id = shipments_row_id
        super().__init__(reason)


@dataclass(frozen=True)
class RouteCompletedDuplicateResult:
    is_duplicate: bool
    lifecycle_id: str | None = None
    shipments_row_id: str | None = None

@dataclass(frozen=True)
class RouteCompletedIngressGateResult:
    skip: bool
    reason: str | None = None

@dataclass(frozen=True)
class PodEmailReceivedPrepareResult:
    workflow_payload: dict[str, Any] | None = None
    is_duplicate: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    shipments_row_id: str | None = None

@dataclass(frozen=True)
class PodEmailReceivedResolution:
    shipments_row_id: str
    shipment_number: str
    workflow_lifecycle_id: str | None
    resolution_source: str


class PodLifecycleIngressService:
    """Ingress checks and payload enrichment before ``pod_lifecycle`` graph runs."""

    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        runs_service: WorkflowRunsService | None = None,
        shipments_service: ShipmentsService | None = None,
        communications_service: CommunicationsService | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()
        self._runs_service = runs_service or WorkflowRunsService()
        self._shipments = shipments_service or ShipmentsService()
        self._communications = communications_service or CommunicationsService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def _resolve_shipments_row_id(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        row_id = self._clean(payload.get("shipments_row_id"))
        if row_id:
            return row_id

        external = self._clean(payload.get("shipment_id"))
        if not external:
            return None

        row = self._shipments.get_by_shipment_number(
            tenant_id=tenant_id,
            shipment_number=external,
        )
        if not row:
            return None
        return self._clean(row.get("id"))

    def _shipment_number_for_row(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        external = self._clean(payload.get("shipment_id"))
        row = self._shipments.get_by_id(
            tenant_id=tenant_id,
            shipment_id=shipments_row_id,
        )
        if row:
            number = self._clean(row.get("shipment_number"))
            if number:
                return number
        return external

    def _require_ratecon_lifecycle(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
    ) -> None:
        lifecycle = self._lifecycle_service.read_lifecycle(
            tenant_id=tenant_id,
            workflow_name=RATECON_GATE_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        if lifecycle.get("found"):
            return
        raise PodEmailIngressSkipped(
            "no_ratecon_workflow_lifecycle",
            shipments_row_id=shipments_row_id,
        )

    def _pod_lifecycle_id_for_shipment(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
    ) -> str | None:
        lifecycle = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tenant_id,
            workflow_name=POD_LIFECYCLE_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        if not lifecycle.get("exists"):
            return None
        return self._clean(lifecycle.get("lifecycle_id"))

    def _pick_thread_context(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[str, str, str | None] | None:
        thread_shipment_context = resolve_primary_shipment_from_thread_rows(
            rows,
            pod_workflow_name=POD_LIFECYCLE_WORKFLOW,
        )
        if thread_shipment_context is None:
            return None
        return (
            thread_shipment_context.shipments_row_id,
            thread_shipment_context.shipment_number,
            thread_shipment_context.pod_lifecycle_id,
        )

    def _apply_resolution(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        resolution: PodEmailReceivedResolution,
    ) -> dict[str, Any]:
        enriched_payload = dict(payload)
        enriched_payload["shipments_row_id"] = resolution.shipments_row_id
        enriched_payload["shipment_id"] = resolution.shipment_number
        if resolution.workflow_lifecycle_id:
            enriched_payload["workflow_lifecycle_id"] = resolution.workflow_lifecycle_id
        logger.info(
            "pod email ingress resolved tenant_id=%s thread_id=%s source=%s "
            "shipments_row_id=%s shipment_id=%s workflow_lifecycle_id=%s",
            tenant_id,
            self._clean(payload.get("thread_id")),
            resolution.resolution_source,
            resolution.shipments_row_id,
            resolution.shipment_number,
            resolution.workflow_lifecycle_id,
        )
        return enriched_payload

    async def _finish_email_resolution(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        tenant_slug: str,
        resolution: PodEmailReceivedResolution,
    ) -> dict[str, Any]:
        self._require_ratecon_lifecycle(
            tenant_id=tenant_id,
            shipments_row_id=resolution.shipments_row_id,
        )
        slug = self._clean(tenant_slug)
        if not slug:
            raise Exception(
                "pod_lifecycle email_received: missing tenant_slug for status check"
            )
        try:
            turvo_payload = await get_shipment(slug, resolution.shipment_number)
        except Exception as turvo_error:
            logger.warning(
                "pod email ingress: turvo get_shipment failed tenant_slug=%s "
                "shipment_id=%s error=%s",
                slug,
                resolution.shipment_number,
                turvo_error,
            )
            raise PodEmailIngressSkipped(
                POD_EMAIL_SKIP_TURVO_FETCH_FAILED,
                shipments_row_id=resolution.shipments_row_id,
            ) from turvo_error
        if not pod_email_status_eligible_from_turvo_payload(turvo_payload):
            raise PodEmailIngressSkipped(
                POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS,
                shipments_row_id=resolution.shipments_row_id,
            )
        return self._apply_resolution(
            payload,
            tenant_id=tenant_id,
            resolution=resolution,
        )

    async def prepare_email_received_payload(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Resolve shipment + optional existing pod lifecycle before graph correlation.

        Requires a ``ratecon`` workflow_lifecycle for the resolved ``shipments`` row.
        Mirrors manual upload keys: ``shipments_row_id``, Turvo ``shipment_id``,
        and ``workflow_lifecycle_id`` when a pod lifecycle already exists.
        """
        tenant_id_clean = self._clean(tenant_id)
        if not tenant_id_clean:
            raise Exception("pod_lifecycle email_received: missing tenant_id")

        existing_row_id = self._resolve_shipments_row_id(
            tenant_id=tenant_id_clean, payload=payload
        )
        if existing_row_id:
            shipment_number = self._shipment_number_for_row(
                tenant_id=tenant_id_clean,
                shipments_row_id=existing_row_id,
                payload=payload,
            )
            if not shipment_number:
                raise Exception(
                    "pod_lifecycle email_received: could not resolve Turvo shipment_number "
                    f"for shipments_row_id={existing_row_id!r}"
                )
            pod_lifecycle_id = self._pod_lifecycle_id_for_shipment(
                tenant_id=tenant_id_clean,
                shipments_row_id=existing_row_id,
            )
            return await self._finish_email_resolution(
                payload,
                tenant_id=tenant_id_clean,
                tenant_slug=tenant_slug,
                resolution=PodEmailReceivedResolution(
                    shipments_row_id=existing_row_id,
                    shipment_number=shipment_number,
                    workflow_lifecycle_id=pod_lifecycle_id,
                    resolution_source="payload",
                ),
            )

        thread_id = self._clean(payload.get("thread_id"))
        if thread_id:
            thread_context_rows = self._communications.find_shipment_context_for_thread(
                tenant_id=tenant_id_clean,
                thread_id=thread_id,
            )
            thread_shipment_context = self._pick_thread_context(thread_context_rows)
            if thread_shipment_context:
                shipments_row_id, shipment_number, pod_lifecycle_id = (
                    thread_shipment_context
                )
                if not pod_lifecycle_id:
                    pod_lifecycle_id = self._pod_lifecycle_id_for_shipment(
                        tenant_id=tenant_id_clean,
                        shipments_row_id=shipments_row_id,
                    )
                return await self._finish_email_resolution(
                    payload,
                    tenant_id=tenant_id_clean,
                    tenant_slug=tenant_slug,
                    resolution=PodEmailReceivedResolution(
                        shipments_row_id=shipments_row_id,
                        shipment_number=shipment_number,
                        workflow_lifecycle_id=pod_lifecycle_id,
                        resolution_source="thread",
                    ),
                )

        raise PodEmailIngressSkipped(
            "no_shipment_context",
            shipments_row_id=None,
        )

    async def prepare_pod_email_received_for_ingress(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> PodEmailReceivedPrepareResult:
        """
        Single ingress pass: resolve shipment, Turvo guards, and duplicate check.

        Sets ``pod_email_ingress_prepared`` on the returned payload so ``WorkflowService.run``
        can skip a second prepare when the email already passed L2 ingress.
        """
        workflow_payload = {**payload, "event_type": "email_received"}
        try:
            prepared_payload = await self.prepare_email_received_payload(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                payload=workflow_payload,
            )
        except PodEmailIngressSkipped as skip:
            return PodEmailReceivedPrepareResult(
                skipped=True,
                skip_reason=skip.reason,
                shipments_row_id=skip.shipments_row_id,
            )

        is_duplicate = self.is_duplicate_email_pod_ingest(
            tenant_id=tenant_id,
            payload=prepared_payload,
        )
        prepared_payload["pod_email_ingress_prepared"] = True
        return PodEmailReceivedPrepareResult(
            workflow_payload=prepared_payload,
            is_duplicate=is_duplicate,
        )

    def check_route_completed_duplicate(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> RouteCompletedDuplicateResult:
        """
        Return whether this ``route_completed`` payload is a duplicate.

        Uses read-only lifecycle lookup (no row creation) then ``workflow_runs``.
        """
        event_type = self._clean(payload.get("event_type"))
        if event_type != WorkflowRunEventType.ROUTE_COMPLETED.value:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        tenant_id_clean = self._clean(tenant_id)
        if not tenant_id_clean:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        shipments_row_id = self._resolve_shipments_row_id(
            tenant_id=tenant_id_clean,
            payload=payload,
        )
        if not shipments_row_id:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        lifecycle = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tenant_id_clean,
            workflow_name=POD_LIFECYCLE_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        if not lifecycle.get("exists"):
            return RouteCompletedDuplicateResult(
                is_duplicate=False,
                shipments_row_id=shipments_row_id,
            )

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id"))
        if not lifecycle_id:
            return RouteCompletedDuplicateResult(
                is_duplicate=False,
                shipments_row_id=shipments_row_id,
            )

        blocked = self._runs_service.is_workflow_initial_path_blocked(
            tenant_id=tenant_id_clean,
            event_type=WorkflowRunEventType.ROUTE_COMPLETED.value,
            workflow_lifecycle_id=lifecycle_id,
            shipment_id=shipments_row_id,
            exclude_run_id=None,
        )
        return RouteCompletedDuplicateResult(
            is_duplicate=blocked,
            lifecycle_id=lifecycle_id,
            shipments_row_id=shipments_row_id,
        )

    async def check_route_completed_convoy_gate(
        self,
        *,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> RouteCompletedIngressGateResult:
        """Skip route_completed ingress when Turvo shipment is a Convoy load."""
        if self._clean(payload.get("event_type")) != WorkflowRunEventType.ROUTE_COMPLETED.value:
            return RouteCompletedIngressGateResult(skip=False)

        slug = self._clean(tenant_slug)
        shipment_id = self._clean(payload.get("shipment_id"))
        if not slug or not shipment_id:
            return RouteCompletedIngressGateResult(skip=False)

        try:
            shipment = await get_shipment(slug, shipment_id)
        except Exception as exc:
            logger.warning(
                "pod route_completed ingress: turvo get_shipment failed tenant_slug=%s "
                "shipment_id=%s error=%s",
                slug,
                shipment_id,
                exc,
            )
            return RouteCompletedIngressGateResult(skip=False)

        if is_convoy_from_turvo_shipment_payload(shipment):
            logger.info(
                "pod route_completed ingress: convoy load skipped tenant_slug=%s shipment_id=%s",
                slug,
                shipment_id,
            )
            return RouteCompletedIngressGateResult(
                skip=True,
                reason=ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
            )
        return RouteCompletedIngressGateResult(skip=False)

    async def check_route_completed_pod_gate(
        self,
        *,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> RouteCompletedIngressGateResult:
        """Skip route_completed ingress when Turvo documents list already has POD."""
        if self._clean(payload.get("event_type")) != WorkflowRunEventType.ROUTE_COMPLETED.value:
            return RouteCompletedIngressGateResult(skip=False)

        slug = self._clean(tenant_slug)
        shipment_id = self._clean(payload.get("shipment_id"))
        if not slug or not shipment_id:
            return RouteCompletedIngressGateResult(skip=False)

        result = await check_pod_by_shipment_id(slug, shipment_id)
        if result.get("success") and result.get("pod_exists"):
            logger.info(
                "pod route_completed ingress: POD already exists tenant_slug=%s shipment_id=%s",
                slug,
                shipment_id,
            )
            return RouteCompletedIngressGateResult(
                skip=True,
                reason=ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
            )
        return RouteCompletedIngressGateResult(skip=False)

    def _resolve_email_pod_lifecycle_id(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Read-only shipment/thread resolution for duplicate email gate (no upserts)."""
        tenant_id_clean = self._clean(tenant_id)
        if not tenant_id_clean:
            return None

        existing_row_id = self._resolve_shipments_row_id(
            tenant_id=tenant_id_clean, payload=payload
        )
        if existing_row_id:
            return self._pod_lifecycle_id_for_shipment(
                tenant_id=tenant_id_clean,
                shipments_row_id=existing_row_id,
            )

        thread_id = self._clean(payload.get("thread_id"))
        if not thread_id:
            return None

        thread_context_rows = self._communications.find_shipment_context_for_thread(
            tenant_id=tenant_id_clean,
            thread_id=thread_id,
        )
        thread_shipment_context = self._pick_thread_context(thread_context_rows)
        if not thread_shipment_context:
            return None

        shipments_row_id, _, pod_lifecycle_id = thread_shipment_context
        if pod_lifecycle_id:
            return pod_lifecycle_id
        return self._pod_lifecycle_id_for_shipment(
            tenant_id=tenant_id_clean,
            shipments_row_id=shipments_row_id,
        )

    def is_duplicate_email_pod_ingest(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """True when lifecycle sub_status is at or past ``document_processed``."""
        lifecycle_id = self._resolve_email_pod_lifecycle_id(
            tenant_id=tenant_id,
            payload=payload,
        )
        if not lifecycle_id:
            return False

        row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id)
        sub_status = sub_status_type_from_db(row.get("sub_status") if row else None)
        return is_pod_processing_complete_sub_status(sub_status)
