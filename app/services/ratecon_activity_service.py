"""Ratecon workflow activity logging (received, upload, processed / soft-complete)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_ratecon_document_processed_with_llm_action,
    format_ratecon_document_processing_failed_action,
    format_ratecon_document_upload_failed_action,
    format_ratecon_document_uploaded_action,
    format_ratecon_received_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.workflows.shipment_resolver import resolve_shipments_row_id_for_db

if TYPE_CHECKING:
    from app.domain.state import WorkflowState

logger = get_logger(__name__)


def _scope_ids(state: WorkflowState) -> tuple[str, str, str] | None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def _communication_id(state: WorkflowState) -> str | None:
    raw = state.data.get("communication_id")
    if raw is None:
        return None
    cid = str(raw).strip()
    return cid or None


def _ratecon_received_metadata(state: WorkflowState) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("load_id", "thread_id", "shipment_id", "shipments_row_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta[key] = str(raw).strip()
    return meta


def upload_success(upload_result: dict[str, Any] | None) -> bool:
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


def analysis_success(state: WorkflowState) -> bool:
    persist = state.data.get("document_analysis_ratecon")
    return isinstance(persist, dict) and persist.get("stored") is True


def _processed_success_metadata(state: WorkflowState) -> dict[str, Any]:
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


def _processed_failure_metadata(state: WorkflowState) -> dict[str, Any]:
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


def _soft_complete_metadata(state: WorkflowState) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "ratecon_soft_complete"}
    upload_result = state.data.get("ratecon_s3_upload")
    if isinstance(upload_result, dict):
        meta["ratecon_s3_upload"] = upload_result
    results = state.data.get("ratecon_analysis_results")
    if isinstance(results, dict):
        meta["ratecon_analysis_results"] = results
    for key in ("shipment_id", "shipments_row_id", "load_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta[key] = str(raw).strip()
    return meta


class RateconActivityService:
    """Record ratecon lifecycle activity steps."""

    def __init__(
        self,
        *,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self._activity_log_service = activity_log_service or ActivityLogService()

    def record_received(self, state: WorkflowState) -> None:
        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "RateconActivityService.record_received skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        meta = _ratecon_received_metadata(state)
        comm_id = _communication_id(state)

        self._activity_log_service.record_sequence(
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

    def record_upload(self, state: WorkflowState) -> None:
        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "RateconActivityService.record_upload skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        upload_result = state.data.get("ratecon_s3_upload")

        if upload_success(upload_result if isinstance(upload_result, dict) else None):
            meta = _upload_success_metadata(upload_result)
            self._activity_log_service.record_sequence(
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
            return

        fail_meta = _upload_failure_metadata(
            upload_result if isinstance(upload_result, dict) else None
        )
        self._activity_log_service.record_sequence(
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
                ),
            )
        )

    def record_processed(self, state: WorkflowState) -> None:
        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "RateconActivityService.record_processed skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        shipments_row_id = resolve_shipments_row_id_for_db(state.data)
        if not shipments_row_id:
            logger.warning(
                "RateconActivityService.record_processed skipped missing shipments_row_id"
            )
            return

        wl_id, tenant_id, run_id = scope
        upload_ok = upload_success(
            state.data.get("ratecon_s3_upload")
            if isinstance(state.data.get("ratecon_s3_upload"), dict)
            else None
        )
        analysis_ok = analysis_success(state)

        if analysis_ok:
            meta = _processed_success_metadata(state)
            results = state.data.get("ratecon_analysis_results")
            if not isinstance(results, dict):
                results = {}
            try:
                confidence = float(results.get("confidence_score"))
            except (TypeError, ValueError):
                confidence = None
            comm_id = _communication_id(state)
            self._activity_log_service.record_sequence(
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
            return

        if upload_ok:
            fail_meta = _processed_failure_metadata(state)
            self._activity_log_service.record_sequence(
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
                            to_status=StatusType.COMPLETED,
                            to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                            from_status=StatusType.PROCESSING,
                            from_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                            metadata=fail_meta,
                        ),
                    ),
                )
            )
            return

        soft_meta = _soft_complete_metadata(state)
        if not upload_ok:
            soft_meta["document_upload"] = "failed_or_skipped"
        if not analysis_ok:
            soft_meta["document_analysis"] = "failed_or_skipped"
        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_ratecon_document_processing_failed_action(),
                        metadata=soft_meta,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.RATECON_STARTED,
                        from_status=StatusType.PROCESSING,
                        from_sub_status=StatusSubType.RATECON_STARTED,
                        metadata=soft_meta,
                    ),
                ),
            )
        )
