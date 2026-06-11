"""Record portal user acknowledgement of a PoD review (portal lifecycle-scoped ACTION)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.activity_log_descriptions import format_pod_review_acknowledged_action
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.api_user import ApiUser
from app.models.activity_type import ActorType
from app.services.activity_log_service import ActivityLogService
from app.services.pod_tms_upload_service import (
    PodLifecycleNotFoundError,
    PodTmsUploadService,
)


@dataclass(frozen=True)
class PodReviewAcknowledgeResult:
    shipment_id: str
    workflow_lifecycle_id: str
    activity_log_id: str


class PodReviewAcknowledgeService:
    def __init__(
        self,
        *,
        pod_service: PodTmsUploadService | None = None,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self._pod = pod_service or PodTmsUploadService()
        self._activity_logs = activity_log_service or ActivityLogService()

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def acknowledge(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        comment: str,
        user: ApiUser,
    ) -> PodReviewAcknowledgeResult:
        cleaned_comment = self._clean(comment)
        if not cleaned_comment:
            raise ValueError("comment is required")

        resolution = self._pod.resolve_pod_lifecycle(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id.strip(),
        )

        activity_log_id = self._activity_logs.record_action(
            ActivityLogWrite(
                tenant_id=tenant_slug,
                workflow_lifecycle_id=resolution.workflow_lifecycle_id,
                workflow_run_id=None,
                description=format_pod_review_acknowledged_action(),
                metadata={
                    "comment": cleaned_comment,
                    "shipment_id": resolution.shipment_number,
                    "shipments_row_id": resolution.shipments_row_id,
                    "workflow_lifecycle_id": resolution.workflow_lifecycle_id,
                },
                actor_type=ActorType.USER,
                actor_id=str(user.id),
            )
        )
        if not activity_log_id:
            raise RuntimeError("failed to record PoD review acknowledgement")

        return PodReviewAcknowledgeResult(
            shipment_id=resolution.shipments_row_id,
            workflow_lifecycle_id=resolution.workflow_lifecycle_id,
            activity_log_id=activity_log_id,
        )
