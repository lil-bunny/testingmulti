"""Supersede prior ratecon (and in-progress DA) before a new ratecon workflow run."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.workflow_cancel_trigger import (
    RATECON_SUPERSEDED_TRIGGER,
    WorkflowCancelTrigger,
)
from app.services.communications.service import CommunicationsService
from app.services.workflow_lifecycle_cancel_orchestrator import (
    WorkflowLifecycleCancelOrchestrator,
)

if TYPE_CHECKING:
    from app.services.workflow_lifecycle_cancel_service import WorkflowCancelResult

logger = get_logger(__name__)


class RateconSupersedeService:
    def __init__(
        self,
        *,
        orchestrator: WorkflowLifecycleCancelOrchestrator | None = None,
        communications: CommunicationsService | None = None,
    ) -> None:
        self._orchestrator = orchestrator or WorkflowLifecycleCancelOrchestrator()
        self._communications = communications or CommunicationsService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def supersede_before_run(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        shipments_row_id: str,
        load_id: str | None = None,
        shipment_id: str | None = None,
        communication_id: str | None = None,
    ) -> dict[str, WorkflowCancelResult]:
        comm_id = self._clean(communication_id)
        if comm_id and self._communications.is_communication_linked_to_run(
            communication_id=comm_id,
        ):
            logger.info(
                "ratecon supersede skipped comm already linked tenant=%s comm_id=%s",
                tenant_slug,
                comm_id,
            )
            return {}

        row_id = self._clean(shipments_row_id)
        if not row_id:
            return {}

        meta: dict[str, Any] = {}
        clean_load = self._clean(load_id)
        clean_shipment = self._clean(shipment_id)
        if clean_load:
            meta["load_id"] = clean_load
        if clean_shipment:
            meta["shipment_id"] = clean_shipment

        trigger = WorkflowCancelTrigger(
            trigger=RATECON_SUPERSEDED_TRIGGER,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            shipments_row_id=row_id,
            load_id=clean_load,
            shipment_number=clean_shipment,
            metadata=meta,
        )
        results = self._orchestrator.cancel_for_trigger(trigger)
        ratecon = results.get("ratecon")
        if ratecon and ratecon.cancelled:
            logger.info(
                "ratecon supersede cancelled prior lifecycle_id=%s tenant=%s load_id=%s",
                ratecon.lifecycle_id,
                tenant_slug,
                trigger.load_id,
            )
        da = results.get("driver_assignment")
        if da and da.cancelled:
            logger.info(
                "driver_assignment supersede cancelled prior lifecycle_id=%s tenant=%s load_id=%s",
                da.lifecycle_id,
                tenant_slug,
                trigger.load_id,
            )
        elif da and da.skip_reason and da.skip_reason not in ("not_found", "no_active_lifecycle"):
            logger.info(
                "driver_assignment supersede skipped reason=%s tenant=%s load_id=%s",
                da.skip_reason,
                tenant_slug,
                trigger.load_id,
            )
        return results
