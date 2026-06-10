"""Activity log nodes for the ``ratecon`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_ratecon_document_processed_with_llm_action,
    format_ratecon_document_processing_failed_action,
    format_ratecon_document_upload_failed_action,
    format_ratecon_document_uploaded_action,
    format_ratecon_received_action,
)
from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogStep,
)
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService

logger = get_logger(__name__)


def _scope_ids(state) -> tuple[str, str, str] | None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def _ratecon_received_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("load_id", "thread_id", "shipment_id", "shipments_row_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta[key] = str(raw).strip()
    return meta


def _upload_success(upload_result: dict[str, Any] | None) -> bool:
    if not isinstance(upload_result, dict):
        return False
    if upload_result.get("skipped"):
        return False
    if not upload_result.get("all_succeeded"):
        return False
    for item in upload_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        persist = item.get("document_persist") or {}
        if persist.get("stored"):
            return True
    return False


def _upload_failure_metadata(upload_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(upload_result, dict):
        return {"reason": "missing_ratecon_s3_upload"}
    meta: dict[str, Any] = {"ratecon_s3_upload": upload_result}
    reason = upload_result.get("reason")
    if reason is not None and str(reason).strip():
        meta["reason"] = str(reason).strip()
        return meta
    for item in upload_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        err = item.get("error_message")
        if err is not None and str(err).strip():
            meta["reason"] = str(err).strip()
            return meta
    meta["reason"] = "ratecon_upload_not_succeeded"
    return meta


def _upload_success_metadata(upload_result: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    keys: list[str] = []
    doc_ids: list[str] = []
    for item in upload_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("object_key")
        if key is not None and str(key).strip():
            keys.append(str(key).strip())
        persist = item.get("document_persist") or {}
        doc_id = persist.get("id")
        if doc_id is not None and str(doc_id).strip():
            doc_ids.append(str(doc_id).strip())
    if keys:
        meta["object_key"] = keys[0]
        meta["object_keys"] = keys
    if doc_ids:
        meta["document_id"] = doc_ids[0]
        meta["document_ids"] = doc_ids
    return meta


def _analysis_success(state) -> bool:
    persist = state.data.get("document_analysis_ratecon")
    return isinstance(persist, dict) and persist.get("stored") is True


def _processed_success_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "ratecon_analysis"}
    persist = state.data.get("document_analysis_ratecon")
    if isinstance(persist, dict):
        analysis_id = persist.get("id")
        if analysis_id is not None and str(analysis_id).strip():
            meta["document_analysis_id"] = str(analysis_id).strip()
    results = state.data.get("ratecon_analysis_results")
    if isinstance(results, dict):
        meta["output"] = results
        if results.get("confidence_score") is not None:
            meta["confidence_score"] = results.get("confidence_score")
        document_id = results.get("document_id")
        if document_id is not None and str(document_id).strip():
            meta["document_id"] = str(document_id).strip()
    for key in ("shipment_id", "shipments_row_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta["shipment_id"] = str(raw).strip()
            break
    return meta


def _processed_failure_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    results = state.data.get("ratecon_analysis_results")
    if isinstance(results, dict):
        meta["ratecon_analysis_results"] = results
        reason = results.get("reason") or results.get("error")
        if reason is not None and str(reason).strip():
            meta["reason"] = str(reason).strip()
            return meta
    persist = state.data.get("document_analysis_ratecon")
    if isinstance(persist, dict):
        meta["document_analysis_ratecon"] = persist
    meta["reason"] = "ratecon_analysis_not_stored"
    return meta


def _communication_id(state) -> str | None:
    raw = state.data.get("communication_id")
    if raw is None:
        return None
    cid = str(raw).strip()
    return cid or None


def record_ratecon_received_activity(state):
    """
    Log ratecon received action + processing status for this lifecycle/run.

    Runs after ``resolve_workflow_lifecycle`` once ``workflow_runs`` exists.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_ratecon_received_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    meta = _ratecon_received_metadata(state)
    comm_id = _communication_id(state)

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_ratecon_received_action(),
                    metadata=meta,
                    communication_id=comm_id,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PROCESSING,
                    to_sub_status=StatusSubType.RATECON_STARTED,
                    from_status=StatusType.NONE,
                    from_sub_status=StatusSubType.NONE,
                    metadata=meta,
                    communication_id=comm_id,
                ),
            ),
        )
    )
    return state


def record_ratecon_upload_activity(state):
    """
    Log document upload outcome for this run.

    Success: action + sub_status document_uploaded (lifecycle stays processing).
    Failure: action + failed status.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_ratecon_upload_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    upload_result = state.data.get("ratecon_s3_upload")
    activity_log_service = ActivityLogService()

    if _upload_success(upload_result if isinstance(upload_result, dict) else None):
        meta = _upload_success_metadata(upload_result)
        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_ratecon_document_uploaded_action(),
                        metadata=meta,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                        from_sub_status=StatusSubType.RATECON_STARTED,
                        metadata=meta,
                    ),
                ),
            )
        )
        return state

    fail_meta = _upload_failure_metadata(
        upload_result if isinstance(upload_result, dict) else None
    )
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_ratecon_document_upload_failed_action(),
                    metadata=fail_meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.FAILED,
                    from_status=StatusType.PROCESSING,
                    metadata=fail_meta,
                ),
            ),
        )
    )
    return state


def record_ratecon_processed_activity(state):
    """
    Log ratecon analysis outcome and final lifecycle status for this run.

    Success: action + completed/document_processed.
    Failure after upload: action + failed status (sub_status stays document_uploaded).
    Skips when upload failed (upload node already logged failure).
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_ratecon_processed_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    upload_result = state.data.get("ratecon_s3_upload")
    if not _upload_success(upload_result if isinstance(upload_result, dict) else None):
        return state

    wl_id, tenant_id, run_id = scope
    activity_log_service = ActivityLogService()

    if _analysis_success(state):
        meta = _processed_success_metadata(state)
        results = state.data.get("ratecon_analysis_results")
        if not isinstance(results, dict):
            results = {}
        try:
            confidence = float(results.get("confidence_score"))
        except (TypeError, ValueError):
            confidence = None
        comm_id = _communication_id(state)
        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_ratecon_document_processed_with_llm_action(
                            confidence=confidence,
                        ),
                        metadata=meta,
                        communication_id=comm_id,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.DOCUMENT_PROCESSED,
                        from_status=StatusType.PROCESSING,
                        from_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                        metadata=meta,
                    ),
                ),
            )
        )
        return state

    fail_meta = _processed_failure_metadata(state)
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_ratecon_document_processing_failed_action(),
                    metadata=fail_meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.FAILED,
                    from_status=StatusType.PROCESSING,
                    metadata=fail_meta,
                ),
            ),
        )
    )
    return state
