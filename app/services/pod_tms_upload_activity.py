"""Activity log transitions for POD TMS upload (API v1; not wired to LangGraph)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from app.core.logger import get_logger
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
from app.domain.error_catalog import IntegrationError
from app.domain.pod_activity_metadata import tms_action_metadata
from app.domain.pod_lifecycle_guards import is_manual_pod_upload
from app.domain.state import WorkflowState
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)

PodTmsUploadOutcome = Literal["uploaded", "skipped", "failed"]


@dataclass(frozen=True)
class PodLifecycleScope:
    tenant_id: str
    workflow_lifecycle_id: str
    workflow_run_id: str | None
    shipments_row_id: str | None
    from_status: StatusType
    from_sub_status: StatusSubType


def _manual_normalize_step(scope: PodLifecycleScope) -> ActivityLogStep | None:
    """Manual portal: reset stale ``pending_review`` before TMS completion."""
    if scope.from_status != StatusType.PENDING_REVIEW:
        return None
    return ActivityLogStep(
        activity_type=ActivityType.STATUS_CHANGE,
        from_status=StatusType.PENDING_REVIEW,
        to_status=StatusType.PROCESSING,
        from_sub_status=scope.from_sub_status,
        to_sub_status=scope.from_sub_status,
        metadata=None,
    )


def _completion_scope(scope: PodLifecycleScope, *, is_manual: bool) -> PodLifecycleScope:
    if is_manual and scope.from_status == StatusType.PENDING_REVIEW:
        return replace(scope, from_status=StatusType.PROCESSING)
    return scope


def _completed_transition_step(
    *,
    scope: PodLifecycleScope,
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
            metadata=None,
        )
    if needs_sub:
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            from_sub_status=scope.from_sub_status,
            to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            metadata=None,
        )
    return None


def _completed_steps(
    *,
    outcome: PodTmsUploadOutcome,
    scope: PodLifecycleScope,
    action_description: str,
    extra: dict[str, Any] | None = None,
    is_manual: bool = False,
) -> tuple[ActivityLogStep, ...]:
    action_meta = tms_action_metadata(outcome=outcome, extra=extra)
    steps: list[ActivityLogStep] = []
    if is_manual:
        normalize = _manual_normalize_step(scope)
        if normalize is not None:
            steps.append(normalize)
    steps.append(
        ActivityLogStep(
            activity_type=ActivityType.ACTION,
            description=action_description,
            metadata=action_meta,
        ),
    )
    completion_scope = _completion_scope(scope, is_manual=is_manual)
    transition = _completed_transition_step(scope=completion_scope)
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
    is_manual: bool = False,
) -> ActivityLogSequenceResult | None:
    """Write activity log + lifecycle transition for POD TMS upload outcome."""
    del shadow_state_data, shipment_id  # lifecycle row scopes timeline; metadata is allowlist-only
    svc = activity_log_service or ActivityLogService()
    extra = dict(extra_metadata or {})
    optimization = extra.pop("optimization", None)
    if isinstance(optimization, dict) and optimization.get("optimized") is True:
        extra["optimization"] = optimization

    if outcome in ("uploaded", "skipped"):
        action_description = (
            format_pod_uploaded_to_tms_action()
            if outcome == "uploaded"
            else format_pod_already_on_tms_action()
        )
        steps = _completed_steps(
            outcome=outcome,
            scope=scope,
            action_description=action_description,
            extra=extra or None,
            is_manual=is_manual,
        )
    else:
        action_meta = tms_action_metadata(outcome=outcome, extra=extra or None)
        steps = (
            ActivityLogStep(
                activity_type=ActivityType.ACTION,
                description=format_pod_upload_to_tms_failed_action(),
                metadata=action_meta,
            ),
            ActivityLogStep(
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=scope.from_status,
                to_status=StatusType.FAILED,
                metadata=None,
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
    transition = _completed_transition_step(scope=scope)
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


def _resolve_actor(state: WorkflowState) -> tuple[ActorType, str | None]:
    if not is_manual_pod_upload(state.data):
        return ActorType.SYSTEM, None
    user_id = str(state.data.get("uploaded_by_user_id") or "").strip()
    if user_id:
        return ActorType.USER, user_id
    return ActorType.SYSTEM, None


def _upload_outcome(turvo_result: dict[str, Any]) -> PodTmsUploadOutcome:
    if turvo_result.get("success"):
        return "uploaded"
    message = str(turvo_result.get("message") or "").lower()
    if "already" in message:
        return "skipped"
    return "failed"


def record_pod_tms_upload_from_state(state: WorkflowState) -> PodTmsUploadOutcome | None:
    """Read lifecycle, resolve TMS outcome, and record activity + status transitions."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = str(state.data.get("tenant_id") or state.tenant_id or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip()
    shipment_id = str(state.data.get("shipment_id") or "").strip()
    turvo_result = state.data.get("turvo_upload_result") or {}

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "record_pod_tms_upload_from_state skipped missing ids lifecycle_id=%s run_id=%s",
            wl_id or None,
            run_id or None,
        )
        state.data["pod_tms_upload_activity_recorded"] = False
        return None

    row = WorkflowLifecycleService().read_lifecycle_row_by_id(wl_id)
    if not row:
        logger.warning(
            "record_pod_tms_upload_from_state skipped lifecycle row not found id=%s",
            wl_id,
        )
        state.data["pod_tms_upload_activity_recorded"] = False
        return None

    scope = scope_from_lifecycle_row(
        tenant_id=tenant_id,
        workflow_lifecycle_id=wl_id,
        workflow_run_id=run_id,
        lifecycle_row=row,
        shipments_row_id=state.data.get("shipments_row_id"),
    )
    outcome = _upload_outcome(turvo_result if isinstance(turvo_result, dict) else {})
    extra: dict[str, Any] = {}
    doc = turvo_result.get("document") if isinstance(turvo_result, dict) else None
    if isinstance(doc, dict) and doc.get("id"):
        extra["tms_document_id"] = doc["id"]
    optimization = turvo_result.get("optimization") if isinstance(turvo_result, dict) else None
    if isinstance(optimization, dict) and optimization:
        extra["optimization"] = optimization
    if outcome == "failed":
        extra["error_code"] = IntegrationError.TMS_POD_UPLOAD_FAILED.value
        fail_message = str(turvo_result.get("message") or "").strip()
        if fail_message:
            extra["error_message"] = fail_message[:500]
        if isinstance(turvo_result, dict) and turvo_result.get("status_code") is not None:
            extra["turvo_status_code"] = turvo_result.get("status_code")
    uploaded_by = str(state.data.get("uploaded_by") or "").strip()
    if uploaded_by:
        extra["uploaded_by"] = uploaded_by

    actor_type, actor_id = _resolve_actor(state)
    is_manual = is_manual_pod_upload(state.data)

    sequence_result = record_pod_tms_upload_activity(
        scope=scope,
        shipment_id=shipment_id,
        outcome=outcome,
        extra_metadata=extra or None,
        shadow_state_data=state.data,
        actor_type=actor_type,
        actor_id=actor_id,
        is_manual=is_manual,
    )
    state.data["pod_tms_upload_activity_recorded"] = sequence_result is not None
    state.data["pod_tms_upload_outcome"] = outcome
    return outcome
