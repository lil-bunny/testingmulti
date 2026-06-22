"""Portal acknowledge/resolve for any workflow lifecycle (replaces POD-only review services)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.activity_log_descriptions import (
    format_workflow_review_acknowledged_action,
    format_workflow_review_resolved_action,
)
from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogStep,
    ActivityLogWrite,
)
from app.domain.api_user import ApiUser
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.repositories.tenants_db_repository import get_slug_for_tenant_uuid
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService


class WorkflowLifecycleNotFoundError(Exception):
    """Lifecycle missing, or not owned by the caller's tenant."""


@dataclass(frozen=True)
class WorkflowReviewAcknowledgeResult:
    workflow_lifecycle_id: str
    workflow_name: str
    activity_log_id: str


@dataclass(frozen=True)
class WorkflowReviewResolveResult:
    workflow_lifecycle_id: str
    workflow_name: str
    activity_log_ids: list[str]
    to_status: str
    to_sub_status: str


class WorkflowReviewService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._activity_logs = activity_log_service or ActivityLogService()

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _parse_lifecycle_uuid(workflow_lifecycle_id: str) -> str:
        """Return canonical UUID string or raise ``ValueError``."""
        raw = WorkflowReviewService._clean(workflow_lifecycle_id)
        if not raw:
            raise ValueError("workflow_lifecycle_id is required")
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"invalid workflow_lifecycle_id={workflow_lifecycle_id!r} (expected UUID)"
            ) from exc

    @staticmethod
    def _normalize_uuid(value: str | None) -> str | None:
        """Parse UUID string or return None when missing/invalid."""
        raw = WorkflowReviewService._clean(value)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None

    def _load_owned_lifecycle(
        self,
        *,
        user: ApiUser,
        workflow_lifecycle_id: str,
    ) -> tuple[dict, str]:
        """Return lifecycle row + tenant slug; scope via token tenant and lifecycle id."""
        wl = self._parse_lifecycle_uuid(workflow_lifecycle_id)
        user_tenant_uuid = self._normalize_uuid(user.tenant_id)
        if not user_tenant_uuid:
            raise WorkflowLifecycleNotFoundError("workflow lifecycle not found")

        row = self._lifecycle.read_lifecycle_row_by_id(wl)
        if not row:
            raise WorkflowLifecycleNotFoundError("workflow lifecycle not found")

        row_tenant_uuid = self._normalize_uuid(row.get("tenant_id"))
        if row_tenant_uuid != user_tenant_uuid:
            raise WorkflowLifecycleNotFoundError("workflow lifecycle not found")

        tenant_slug = get_slug_for_tenant_uuid(row_tenant_uuid)
        if not tenant_slug:
            raise WorkflowLifecycleNotFoundError("workflow lifecycle not found")
        return row, tenant_slug

    def acknowledge(
        self,
        *,
        workflow_lifecycle_id: str,
        comment: str,
        user: ApiUser,
    ) -> WorkflowReviewAcknowledgeResult:
        """Record comment-only ACTION; used by ``workflow_lifecycles`` acknowledge API."""
        cleaned_comment = self._clean(comment)
        if not cleaned_comment:
            raise ValueError("comment is required")

        row, tenant_slug = self._load_owned_lifecycle(
            user=user,
            workflow_lifecycle_id=workflow_lifecycle_id,
        )
        wl = self._clean(row.get("id")) or self._clean(workflow_lifecycle_id) or ""
        workflow_name = self._clean(row.get("workflow_name")) or ""

        activity_log_id = self._activity_logs.record_action(
            ActivityLogWrite(
                tenant_id=tenant_slug,
                workflow_lifecycle_id=wl,
                workflow_run_id=None,
                description=format_workflow_review_acknowledged_action(),
                metadata={
                    "comment": cleaned_comment,
                    "workflow_lifecycle_id": wl,
                    "workflow_name": workflow_name,
                },
                actor_type=ActorType.USER,
                actor_id=str(user.id),
            )
        )
        if not activity_log_id:
            raise RuntimeError("failed to record workflow review acknowledgement")

        return WorkflowReviewAcknowledgeResult(
            workflow_lifecycle_id=wl,
            workflow_name=workflow_name,
            activity_log_id=activity_log_id,
        )

    def resolve(
        self,
        *,
        workflow_lifecycle_id: str,
        comment: str,
        user: ApiUser,
    ) -> WorkflowReviewResolveResult:
        """Record comment and mark lifecycle completed/resolved_manually; used by resolve API."""
        cleaned_comment = self._clean(comment)
        if not cleaned_comment:
            raise ValueError("comment is required")

        row, tenant_slug = self._load_owned_lifecycle(
            user=user,
            workflow_lifecycle_id=workflow_lifecycle_id,
        )
        wl = self._clean(row.get("id")) or self._clean(workflow_lifecycle_id) or ""
        workflow_name = self._clean(row.get("workflow_name")) or ""

        metadata = {
            "comment": cleaned_comment,
            "workflow_lifecycle_id": wl,
            "workflow_name": workflow_name,
            "resolved_via": "portal",
        }
        sequence_result = self._activity_logs.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_slug,
                workflow_lifecycle_id=wl,
                workflow_run_id=None,
                actor_type=ActorType.USER,
                actor_id=str(user.id),
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_workflow_review_resolved_action(),
                        metadata=metadata,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.RESOLVED_MANUALLY,
                        metadata=metadata,
                    ),
                ),
            )
        )
        if sequence_result is None or not any(sequence_result.activity_log_ids):
            raise RuntimeError("failed to record workflow review resolve")

        activity_log_ids = [
            log_id for log_id in sequence_result.activity_log_ids if log_id
        ]

        return WorkflowReviewResolveResult(
            workflow_lifecycle_id=wl,
            workflow_name=workflow_name,
            activity_log_ids=activity_log_ids,
            to_status=StatusType.COMPLETED.value,
            to_sub_status=StatusSubType.RESOLVED_MANUALLY.value,
        )
