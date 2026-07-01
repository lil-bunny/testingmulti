"""Activity log nodes for the ``pod_lifecycle`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_pod_document_processing_failed_action,
    format_pod_document_upload_failed_action,
    format_pod_document_uploaded_action,
    format_pod_escalation_sent_action,
    format_pod_extraction_processed_action,
    format_pod_vs_ratecon_validated_action,
    format_pod_vs_ratecon_validation_failed_action,
    format_pod_vs_ratecon_validation_skipped_action,
    format_reminder_sent_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.pod_lifecycle_guards import pod_reminder_skip_sub_statuses
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

logger = get_logger(__name__)


def _scope_ids(state) -> tuple[str, str, str] | None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def _pod_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("shipment_id", "shipments_row_id", "thread_id", "load_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta[key] = str(raw).strip()
    wl_id = state.data.get("workflow_lifecycle_id")
    if wl_id is not None and str(wl_id).strip():
        meta["workflow_lifecycle_id"] = str(wl_id).strip()
    return meta


def _communication_id(state) -> str | None:
    raw = state.data.get("communication_id")
    if raw is None:
        return None
    cid = str(raw).strip()
    return cid or None


def _resolve_actor(state) -> tuple[ActorType, str | None]:
    event_type = str(state.data.get("event_type") or "").strip()
    if event_type != WorkflowRunEventType.MANUAL_POD_UPLOAD.value:
        return ActorType.SYSTEM, None
    user_id = str(state.data.get("uploaded_by_user_id") or "").strip()
    if user_id:
        return ActorType.USER, user_id
    return ActorType.SYSTEM, None


_UPLOAD_DONE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_UPLOADED,
        StatusSubType.DOCUMENT_PROCESSED,
    }
)

_PROCESSED_DONE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_PROCESSED,
    }
)


def _pod_document_persist(state) -> dict[str, Any] | None:
    persist = state.data.get("documents_pod")
    return persist if isinstance(persist, dict) else None


def _upload_success_from_state(state) -> bool:
    data = state.data
    pod_persist = _pod_document_persist(state)
    if isinstance(pod_persist, dict) and pod_persist.get("stored") is True:
        return True

    normalization = data.get("attachment_normalization")
    if isinstance(normalization, dict):
        merged_key = data.get("pod_merged_pdf_object_key")
        if normalization.get("success") and merged_key and str(merged_key).strip():
            return True

    event_type = str(data.get("event_type") or "").strip()
    pod_keys = data.get("pod_object_keys") or []
    if event_type == WorkflowRunEventType.MANUAL_POD_UPLOAD.value and pod_keys:
        return True

    return False


def _upload_success_metadata(state) -> dict[str, Any]:
    meta = _pod_metadata(state)
    pod_persist = _pod_document_persist(state)

    merged_key = state.data.get("pod_merged_pdf_object_key")
    if merged_key is not None and str(merged_key).strip():
        meta["object_key"] = str(merged_key).strip()

    source_keys: list[str] = []
    if isinstance(pod_persist, dict):
        doc_id = pod_persist.get("id")
        if doc_id is not None and str(doc_id).strip():
            meta["document_id"] = str(doc_id).strip()
        persist_meta = pod_persist.get("metadata")
        if isinstance(persist_meta, dict):
            raw_keys = persist_meta.get("source_object_keys")
            if isinstance(raw_keys, list):
                source_keys = [str(k).strip() for k in raw_keys if k and str(k).strip()]

    if not source_keys:
        for raw in state.data.get("pod_source_object_keys") or []:
            if raw and str(raw).strip():
                source_keys.append(str(raw).strip())

    if source_keys:
        meta["source_object_keys"] = source_keys

    return meta


def _upload_failure_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = _pod_metadata(state)
    normalization = state.data.get("attachment_normalization")
    if isinstance(normalization, dict):
        meta["attachment_normalization"] = normalization
        reason = normalization.get("error") or normalization.get("reason")
        if reason is not None and str(reason).strip():
            meta["reason"] = str(reason).strip()
            return meta
    meta["reason"] = "pod_s3_upload_not_succeeded"
    return meta


def _analysis_success(state) -> bool:
    persist = state.data.get("document_analysis_pod")
    return isinstance(persist, dict) and persist.get("stored") is True


def _validation_stored(state) -> bool:
    persist = state.data.get("document_analysis_pod_vs_ratecon")
    return isinstance(persist, dict) and persist.get("stored") is True


def _validation_skipped(state) -> bool:
    results = state.data.get("pod_vs_ratecon_analysis_results")
    return isinstance(results, dict) and results.get("skipped") is True


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extraction_action_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "pod_analysis"}
    meta.update(_pod_metadata(state))

    pod_persist = state.data.get("document_analysis_pod")
    if isinstance(pod_persist, dict):
        analysis_id = pod_persist.get("id")
        if analysis_id is not None and str(analysis_id).strip():
            meta["document_analysis_id"] = str(analysis_id).strip()

    pod_results = state.data.get("pod_analysis_results")
    if isinstance(pod_results, dict):
        extraction_conf = _float_or_none(pod_results.get("confidence_score"))
        if extraction_conf is not None:
            meta["extraction_confidence"] = extraction_conf
            meta["confidence_score"] = extraction_conf
        pod_status = pod_results.get("pod_status")
        if pod_status is not None and str(pod_status).strip():
            meta["pod_status"] = str(pod_status).strip()

    return meta


def _vs_ratecon_action_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "pod_vs_ratecon"}
    meta.update(_pod_metadata(state))

    vs_persist = state.data.get("document_analysis_pod_vs_ratecon")
    if isinstance(vs_persist, dict):
        vs_id = vs_persist.get("id")
        if vs_id is not None and str(vs_id).strip():
            meta["validation_document_analysis_id"] = str(vs_id).strip()

    vs_results = state.data.get("pod_vs_ratecon_analysis_results")
    if isinstance(vs_results, dict):
        if vs_results.get("skipped"):
            meta["validation_skipped"] = True
            reason = vs_results.get("reason")
            if reason is not None and str(reason).strip():
                meta["validation_skip_reason"] = str(reason).strip()
        else:
            validation_conf = _float_or_none(vs_results.get("confidence_score"))
            if validation_conf is not None:
                meta["validation_confidence"] = validation_conf
                meta["confidence_score"] = validation_conf
            overall = vs_results.get("overall_status") or vs_results.get("pod_status")
            if overall is not None and str(overall).strip():
                meta["overall_status"] = str(overall).strip()
            summary = vs_results.get("validation_summary")
            if summary is not None and str(summary).strip():
                meta["validation_summary"] = str(summary).strip()[:500]
            error = vs_results.get("error")
            if error is not None and str(error).strip():
                meta["error"] = str(error).strip()
            reason = vs_results.get("reason")
            if reason is not None and str(reason).strip():
                meta["reason"] = str(reason).strip()

    return meta


def _finalize_success_metadata(state) -> dict[str, Any]:
    return _pod_metadata(state)


def _processed_failure_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = _pod_metadata(state)
    results = state.data.get("pod_analysis_results")
    if isinstance(results, dict):
        meta["pod_analysis_results"] = results
        reason = results.get("reason") or results.get("error")
        if reason is not None and str(reason).strip():
            meta["reason"] = str(reason).strip()
            return meta
    persist = state.data.get("document_analysis_pod")
    if isinstance(persist, dict):
        meta["document_analysis_pod"] = persist
    meta["reason"] = "pod_analysis_not_stored"
    return meta


def _sub_status_already_at_or_past(
    row: dict[str, Any] | None,
    *,
    done: frozenset[StatusSubType],
) -> bool:
    if not row:
        return False
    sub = sub_status_type_from_db(row.get("sub_status"))
    if sub is None:
        return False
    return sub in done


def _sub_status_for_reminder_step(step: int) -> StatusSubType | None:
    mapping = {
        1: StatusSubType.REMINDER_1_SENT,
        2: StatusSubType.REMINDER_2_SENT,
        3: StatusSubType.REMINDER_3_SENT,
    }
    return mapping.get(step)


def _build_reminder_transition_step(
    *,
    current_status: StatusType | None,
    new_sub: StatusSubType,
    metadata: dict[str, Any],
) -> ActivityLogStep:
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
            metadata=dict(metadata),
        )
    return ActivityLogStep(
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=to_status,
        to_sub_status=new_sub,
        metadata=dict(metadata),
    )


def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    status = status_type_from_db(row.get("status"))
    sub = sub_status_type_from_db(row.get("sub_status"))
    if status not in (None, StatusType.NONE):
        return True
    if sub not in (None, StatusSubType.NONE, StatusSubType.POD_STARTED):
        return True
    if sub == StatusSubType.POD_STARTED:
        return True
    return False


def record_pod_started_activity(state):
    """
    Log POD lifecycle started after reminders are scheduled on ``route_completed``.

    STATUS_CHANGE only: ``none/processing``, ``none/pod_started``.
    """
    if not state.data.get("reminders_scheduled"):
        logger.info(
            "record_pod_started_activity skipping (reminders not scheduled) lifecycle_id=%s",
            state.data.get("workflow_lifecycle_id"),
        )
        return state

    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_started_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _lifecycle_already_started(row):
        logger.info(
            "record_pod_started_activity skipping already started lifecycle_id=%s",
            wl_id,
        )
        return state

    meta = _pod_metadata(state)
    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PROCESSING,
                    to_sub_status=StatusSubType.POD_STARTED,
                    from_status=StatusType.NONE,
                    from_sub_status=StatusSubType.NONE,
                    metadata=meta,
                ),
            ),
        )
    )
    return state


def record_pod_reminder_activity(state):
    """
    After successful POD reminder email: map ``reminder_step`` to lifecycle sub_status
    and append activity log (steps 1–3).
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id:
        logger.warning(
            "record_pod_reminder_activity missing workflow_lifecycle_id or tenant_id"
        )
        return state

    if not state.data.get("pod_reminder_sent"):
        logger.info(
            "record_pod_reminder_activity skipping (reminder not sent) lifecycle_id=%s",
            wl_id,
        )
        state.data["pod_reminder_status_skipped"] = "reminder_not_sent"
        return state

    raw_step = state.data.get("reminder_step")
    try:
        step = int(raw_step) if raw_step is not None else None
    except (TypeError, ValueError):
        step = None
    if step not in (1, 2, 3):
        logger.warning(
            "record_pod_reminder_activity invalid reminder_step=%r lifecycle_id=%s",
            raw_step,
            wl_id,
        )
        state.data["pod_reminder_status_error"] = "invalid_reminder_step"
        return state

    new_sub = _sub_status_for_reminder_step(step)
    assert new_sub is not None

    lifecycle_service = WorkflowLifecycleService()
    prev = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    skip = delayed_workflow_step_skip_reason(
        prev,
        skip_sub_statuses=pod_reminder_skip_sub_statuses(state.data),
    )
    if skip:
        logger.info(
            "record_pod_reminder_activity skipping lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["pod_reminder_status_skipped"] = skip
        return state

    if not run_id:
        logger.warning(
            "record_pod_reminder_activity success path skipped: missing execution_id lifecycle_id=%s",
            wl_id,
        )
        return state

    transition_meta: dict[str, Any] = {
        "reminder_step": step,
        **_pod_metadata(state),
    }
    communication_id = _communication_id(state)

    current_status = status_type_from_db(prev.get("status")) if prev else None
    transition_step = _build_reminder_transition_step(
        current_status=current_status,
        new_sub=new_sub,
        metadata=transition_meta,
    )

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_reminder_sent_action(step=step),
                    metadata=dict(transition_meta),
                    communication_id=communication_id,
                ),
                transition_step,
            ),
        )
    )

    state.data["pod_reminder_sub_status"] = new_sub.value
    return state


def record_pod_escalation_activity(state):
    """
    Log POD escalation sub_status (no email send).

    Callable from a future ``escalation_due`` graph path; not wired in ``workflow_configs`` yet.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_escalation_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    skip = delayed_workflow_step_skip_reason(
        row,
        skip_sub_statuses=pod_reminder_skip_sub_statuses(state.data),
    )
    if skip:
        logger.info(
            "record_pod_escalation_activity skipping lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["pod_escalation_skipped"] = skip
        return state

    meta = _pod_metadata(state)
    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_escalation_sent_action(),
                    metadata=meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.SUB_STATUS_CHANGE,
                    to_sub_status=StatusSubType.ESCALATED,
                    from_sub_status=StatusSubType.REMINDER_3_SENT,
                    metadata=meta,
                ),
            ),
        )
    )
    state.data["pod_escalation_sub_status"] = StatusSubType.ESCALATED.value
    return state


def record_pod_upload_activity(state):
    """
    Log POD S3 upload outcome after ``classify_attachments``.

    Success: action + sub_status ``document_uploaded``.
    Failure: action + ``failed`` status.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_upload_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _sub_status_already_at_or_past(row, done=_UPLOAD_DONE_SUB_STATUSES):
        logger.info(
            "record_pod_upload_activity skipping already uploaded lifecycle_id=%s",
            wl_id,
        )
        return state

    actor_type, actor_id = _resolve_actor(state)
    activity_log_service = ActivityLogService()
    from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE
    if from_sub is None:
        from_sub = StatusSubType.NONE

    if _upload_success_from_state(state):
        meta = _upload_success_metadata(state)
        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_pod_document_uploaded_action(),
                        metadata=meta,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                        from_sub_status=from_sub,
                        metadata=meta,
                    ),
                ),
            )
        )
        return state

    fail_meta = _upload_failure_metadata(state)
    from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
    if from_status is None or from_status == StatusType.NONE:
        from_status = StatusType.PROCESSING
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            actor_type=actor_type,
            actor_id=actor_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_document_upload_failed_action(),
                    metadata=fail_meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.FAILED,
                    from_status=from_status,
                    metadata=fail_meta,
                ),
            ),
        )
    )
    return state


def record_pod_extraction_activity(state):
    """
    Log POD LLM extraction outcome after ``pod_analysis``.

    ACTION only — no lifecycle sub_status change.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_extraction_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    if not _upload_success_from_state(state):
        return state

    if not _analysis_success(state):
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _sub_status_already_at_or_past(row, done=_PROCESSED_DONE_SUB_STATUSES):
        logger.info(
            "record_pod_extraction_activity skipping already processed lifecycle_id=%s",
            wl_id,
        )
        return state

    pod_results = state.data.get("pod_analysis_results") or {}
    if not isinstance(pod_results, dict):
        pod_results = {}
    confidence = _float_or_none(pod_results.get("confidence_score"))
    meta = _extraction_action_metadata(state)
    actor_type, actor_id = _resolve_actor(state)
    comm_id = _communication_id(state)

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            actor_type=actor_type,
            actor_id=actor_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_extraction_processed_action(
                        confidence=confidence,
                    ),
                    metadata=meta,
                    communication_id=comm_id,
                ),
            ),
        )
    )
    return state


def _vs_ratecon_action_description(state) -> str:
    if _validation_stored(state):
        vs_results = state.data.get("pod_vs_ratecon_analysis_results") or {}
        if not isinstance(vs_results, dict):
            vs_results = {}
        status = (
            vs_results.get("overall_status")
            or vs_results.get("pod_status")
            or "UNKNOWN"
        )
        confidence = _float_or_none(vs_results.get("confidence_score"))
        return format_pod_vs_ratecon_validated_action(
            confidence=confidence,
            status=str(status),
        )

    if _validation_skipped(state):
        vs_results = state.data.get("pod_vs_ratecon_analysis_results") or {}
        if not isinstance(vs_results, dict):
            vs_results = {}
        reason = str(vs_results.get("reason") or "unknown").strip() or "unknown"
        return format_pod_vs_ratecon_validation_skipped_action(reason=reason)

    return format_pod_vs_ratecon_validation_failed_action()


def record_pod_vs_ratecon_activity(state):
    """
    Log POD vs ratecon validation outcome after ``pod_vs_ratecon_analysis``.

    ACTION only — no lifecycle sub_status change.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_vs_ratecon_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    if not _upload_success_from_state(state):
        return state

    if not _analysis_success(state):
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _sub_status_already_at_or_past(row, done=_PROCESSED_DONE_SUB_STATUSES):
        logger.info(
            "record_pod_vs_ratecon_activity skipping already processed lifecycle_id=%s",
            wl_id,
        )
        return state

    vs_results = state.data.get("pod_vs_ratecon_analysis_results")
    if not isinstance(vs_results, dict):
        logger.info(
            "record_pod_vs_ratecon_activity skipping missing results lifecycle_id=%s",
            wl_id,
        )
        return state

    meta = _vs_ratecon_action_metadata(state)
    actor_type, actor_id = _resolve_actor(state)
    comm_id = _communication_id(state)

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            actor_type=actor_type,
            actor_id=actor_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=_vs_ratecon_action_description(state),
                    metadata=meta,
                    communication_id=comm_id,
                ),
            ),
        )
    )
    return state


def record_pod_processed_activity(state):
    """
    Finalize POD processing: ``pending_review`` + ``document_processed`` when extraction succeeded.

    Failure: action + ``failed`` status when extraction did not persist.
    Skips when S3 upload would have failed.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_processed_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    if not _upload_success_from_state(state):
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _sub_status_already_at_or_past(row, done=_PROCESSED_DONE_SUB_STATUSES):
        logger.info(
            "record_pod_processed_activity skipping already processed lifecycle_id=%s",
            wl_id,
        )
        return state

    actor_type, actor_id = _resolve_actor(state)
    activity_log_service = ActivityLogService()

    if _analysis_success(state):
        meta = _finalize_success_metadata(state)
        current_status = status_type_from_db(row.get("status")) if row else None
        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                steps=(
                    _build_reminder_transition_step(
                        current_status=current_status,
                        new_sub=StatusSubType.DOCUMENT_PROCESSED,
                        metadata=meta,
                    ),
                ),
            )
        )
        return state

    fail_meta = _processed_failure_metadata(state)
    from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
    if from_status is None or from_status == StatusType.NONE:
        from_status = StatusType.PROCESSING
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            actor_type=actor_type,
            actor_id=actor_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_document_processing_failed_action(),
                    metadata=fail_meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.FAILED,
                    from_status=from_status,
                    metadata=fail_meta,
                ),
            ),
        )
    )
    return state
