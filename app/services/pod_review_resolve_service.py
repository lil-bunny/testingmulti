"""Record portal user PoD resolve (uploaded outside portal) — mirrors TMS upload completion."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.api_user import ApiUser
from app.domain.activity_log_write import ActivityLogSequenceResult
from app.models.activity_type import ActorType
from app.services.pod_tms_upload_activity import (
    expected_completion_status,
    record_pod_tms_upload_activity,
    scope_from_lifecycle_row,
)
from app.services.pod_tms_upload_service import (
    PodLifecycleNotFoundError,
    PodTmsUploadService,
)
from app.services.workflow_lifecycle_service import WorkflowLifecycleService


@dataclass(frozen=True)
class PodReviewResolveResult:
    shipment_id: str
    workflow_lifecycle_id: str
    activity_log_ids: list[str]
    to_status: str
    to_sub_status: str


class PodReviewResolveService:
    def __init__(
        self,
        *,
        pod_service: PodTmsUploadService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._pod = pod_service or PodTmsUploadService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def resolve(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        comment: str,
        user: ApiUser,
    ) -> PodReviewResolveResult:
        cleaned_comment = self._clean(comment)
        if not cleaned_comment:
            raise ValueError("comment is required")

        resolution = self._pod.resolve_pod_lifecycle(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id.strip(),
        )

        row = self._lifecycle.read_lifecycle_row_by_id(
            resolution.workflow_lifecycle_id
        )
        if not row:
            raise PodLifecycleNotFoundError("pod_lifecycle not found for shipment")

        scope = scope_from_lifecycle_row(
            tenant_id=tenant_slug,
            workflow_lifecycle_id=resolution.workflow_lifecycle_id,
            workflow_run_id=None,
            lifecycle_row=row,
            shipments_row_id=resolution.shipments_row_id,
        )
        to_status, to_sub_status = expected_completion_status(scope)

        sequence_result = record_pod_tms_upload_activity(
            scope=scope,
            shipment_id=resolution.shipment_number,
            outcome="uploaded",
            extra_metadata={
                "comment": cleaned_comment,
                "resolved_via": "portal",
            },
            actor_type=ActorType.USER,
            actor_id=str(user.id),
        )
        if sequence_result is None:
            raise RuntimeError("failed to record PoD review resolve")

        activity_log_ids = [
            log_id for log_id in sequence_result.activity_log_ids if log_id
        ]
        if not activity_log_ids:
            raise RuntimeError("failed to record PoD review resolve")

        return PodReviewResolveResult(
            shipment_id=resolution.shipments_row_id,
            workflow_lifecycle_id=resolution.workflow_lifecycle_id,
            activity_log_ids=activity_log_ids,
            to_status=to_status.value,
            to_sub_status=to_sub_status.value,
        )
