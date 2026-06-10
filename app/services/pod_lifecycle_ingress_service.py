"""Pre-graph duplicate detection for ``pod_lifecycle`` ``route_completed`` events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService

POD_LIFECYCLE_WORKFLOW = "pod_lifecycle"


@dataclass(frozen=True)
class RouteCompletedDuplicateResult:
    is_duplicate: bool
    lifecycle_id: str | None = None
    shipments_row_id: str | None = None


class PodLifecycleIngressService:
    """Read-only checks before queuing or executing pod route-complete workflows."""

    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        runs_service: WorkflowRunsService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()
        self._runs_service = runs_service or WorkflowRunsService()
        self._shipments = shipments_service or ShipmentsService()

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

        tid = self._clean(tenant_id)
        if not tid:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        shipments_row_id = self._resolve_shipments_row_id(
            tenant_id=tid,
            payload=payload,
        )
        if not shipments_row_id:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        lifecycle = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tid,
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
            tenant_id=tid,
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
