"""Activity log transitions for POD TMS upload (API v1; not wired to LangGraph)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.activity_log_descriptions import (
    format_pod_already_on_tms_action,
    format_pod_upload_to_tms_failed_action,
    format_pod_uploaded_to_tms_action,
)
from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogSequenceResult,
    ActivityLogStep,
)
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.domain.tenant_settings.workflow_shadow_mode import shadow_metadata_patch
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService

PodTmsUploadOutcome = Literal["uploaded", "skipped", "failed"]


@dataclass(frozen=True)
class PodLifecycleScope:
    tenant_id: str
    workflow_lifecycle_id: str
    workflow_run_id: str | None
    shipments_row_id: str | None
    from_status: StatusType
    from_sub_status: StatusSubType


def _metadata(
    *,
    shipment_id: str,
    outcome: PodTmsUploadOutcome,
    scope: PodLifecycleScope,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "shipment_id": shipment_id,
        "outcome": outcome,
        "workflow_lifecycle_id": scope.workflow_lifecycle_id,
    }
    if scope.shipments_row_id:
        meta["shipments_row_id"] = scope.shipments_row_id
    if extra:
        meta.update(extra)
    return meta

def _completed_transition_step(
    *,
    scope: PodLifecycleScope,
    meta: dict[str, Any],
) -> ActivityLogStep | None:
    """
    One transition row after the action — same rules as Gelita/ratecon completion.

    - Status not yet ``completed``: single ``status_change`` (status + sub-status).
    - Already ``completed``, sub-status not ``uploaded_to_tms``: ``sub_status_change`` only.
    - Already ``completed`` + ``uploaded_to_tms``: no transition row.
    """
    needs_status = scope.from_status != StatusType.COMPLETED
    needs_sub = scope.from_sub_status != StatusSubType.UPLOADED_TO_TMS

    if needs_status:
        return ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            from_status=scope.from_status,
            to_status=StatusType.COMPLETED,
            from_sub_status=scope.from_sub_status,
            to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            metadata=meta,
        )
    if needs_sub:
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            from_sub_status=scope.from_sub_status,
            to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            metadata=meta,
        )
    return None


def _completed_steps(
    *,
    shipment_id: str,
    outcome: PodTmsUploadOutcome,
    scope: PodLifecycleScope,
    action_description: str,
    extra: dict[str, Any] | None = None,
) -> tuple[ActivityLogStep, ...]:
    meta = _metadata(
        shipment_id=shipment_id,
        outcome=outcome,
        scope=scope,
        extra=extra,
    )
    steps: list[ActivityLogStep] = [
        ActivityLogStep(
            activity_type=ActivityType.ACTION,
            description=action_description,
            metadata=meta,
        ),
    ]
    transition = _completed_transition_step(scope=scope, meta=meta)
    if transition is not None:
        steps.append(transition)
    return tuple(steps)


def record_pod_tms_upload_activity(
    *,
    scope: PodLifecycleScope,
    shipment_id: str,
    outcome: PodTmsUploadOutcome,
    extra_metadata: dict[str, Any] | None = None,
    shadow_state_data: dict[str, Any] | None = None,
    actor_type: ActorType | None = None,
    actor_id: str | None = None,
    activity_log_service: ActivityLogService | None = None,
) -> ActivityLogSequenceResult | None:
    """Write activity log + lifecycle transition for POD TMS upload outcome."""
    svc = activity_log_service or ActivityLogService()
    merged_extra = dict(extra_metadata or {})
    merged_extra.update(shadow_metadata_patch(shadow_state_data))

    if outcome in ("uploaded", "skipped"):
        action_description = (
            format_pod_uploaded_to_tms_action()
            if outcome == "uploaded"
            else format_pod_already_on_tms_action()
        )
        steps = _completed_steps(
            shipment_id=shipment_id,
            outcome=outcome,
            scope=scope,
            action_description=action_description,
            extra=merged_extra or None,
        )
    else:
        meta = _metadata(
            shipment_id=shipment_id,
            outcome=outcome,
            scope=scope,
            extra=merged_extra or None,
        )
        steps = (
            ActivityLogStep(
                activity_type=ActivityType.ACTION,
                description=format_pod_upload_to_tms_failed_action(),
                metadata=meta,
            ),
            ActivityLogStep(
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=scope.from_status,
                to_status=StatusType.FAILED,
                metadata=meta,
            ),
        )

    return svc.record_sequence(
        ActivityLogSequence(
            tenant_id=scope.tenant_id,
            workflow_lifecycle_id=scope.workflow_lifecycle_id,
            workflow_run_id=scope.workflow_run_id,
            actor_type=actor_type or ActorType.SYSTEM,
            actor_id=actor_id,
            steps=steps,
        )
    )


def expected_completion_status(
    scope: PodLifecycleScope,
) -> tuple[StatusType, StatusSubType]:
    """Terminal status after a successful uploaded/skipped/portal-resolve completion."""
    transition = _completed_transition_step(scope=scope, meta={})
    if transition is None:
        return scope.from_status, scope.from_sub_status
    if transition.activity_type == ActivityType.STATUS_CHANGE:
        return (
            transition.to_status or StatusType.COMPLETED,
            transition.to_sub_status or StatusSubType.UPLOADED_TO_TMS,
        )
    return (
        scope.from_status
        if scope.from_status != StatusType.NONE
        else StatusType.COMPLETED,
        transition.to_sub_status or StatusSubType.UPLOADED_TO_TMS,
    )


def scope_from_lifecycle_row(
    *,
    tenant_id: str,
    workflow_lifecycle_id: str,
    workflow_run_id: str | None = None,
    lifecycle_row: dict[str, Any],
    shipments_row_id: str | None = None,
) -> PodLifecycleScope:
    return PodLifecycleScope(
        tenant_id=tenant_id,
        workflow_lifecycle_id=workflow_lifecycle_id,
        workflow_run_id=workflow_run_id,
        shipments_row_id=shipments_row_id,
        from_status=status_type_from_db(lifecycle_row.get("status")) or StatusType.NONE,
        from_sub_status=sub_status_type_from_db(lifecycle_row.get("sub_status"))
        or StatusSubType.NONE,
    )
