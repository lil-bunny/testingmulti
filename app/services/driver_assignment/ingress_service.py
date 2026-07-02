"""Pre-enqueue and pre-graph ingress for ``driver_assignment`` (ratecon_completed)."""

from __future__ import annotations

from app.services.communications.service import CommunicationsService
from app.services.driver_assignment.activity_service import DriverAssignmentActivityService
from app.services.driver_assignment.ingress_driver_details_inbound import (
    IngressDriverDetailsInboundMixin,
)
from app.services.driver_assignment.ingress_eligibility import IngressEligibilityMixin
from app.services.driver_assignment.ingress_email import IngressEmailMixin
from app.services.driver_assignment.ingress_gates import IngressGatesMixin
from app.services.driver_assignment.ingress_ratecon import IngressRateconMixin
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    EligibilityResult,
    EnqueueResult,
    PrepareResult,
    SendReminderResult,
)
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService


class DriverAssignmentIngressService(
    IngressGatesMixin,
    IngressRateconMixin,
    IngressEligibilityMixin,
    IngressEmailMixin,
    IngressDriverDetailsInboundMixin,
):
    """Layers 1–2 ingress and shared layer-3 eligibility for driver assignment."""

    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        runs_service: WorkflowRunsService | None = None,
        shipments_service: ShipmentsService | None = None,
        communications_service: CommunicationsService | None = None,
        activity_service: DriverAssignmentActivityService | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()
        self._runs_service = runs_service or WorkflowRunsService()
        self._shipments = shipments_service or ShipmentsService()
        self._communications = communications_service or CommunicationsService()
        self._activity = activity_service or DriverAssignmentActivityService()


__all__ = (
    "DRIVER_ASSIGNMENT_WORKFLOW",
    "DriverAssignmentIngressService",
    "EligibilityResult",
    "EnqueueResult",
    "PrepareResult",
    "SendReminderResult",
)
