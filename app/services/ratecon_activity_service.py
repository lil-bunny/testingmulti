"""Ratecon workflow activity logging (received, upload, completed)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_ratecon_document_uploaded_action,
    format_ratecon_document_upload_failed_action,
    format_ratecon_received_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService

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
        upload_result = (
            state.data.get("ratecon_s3_upload")
            if isinstance(state.data.get("ratecon_s3_upload"), dict)
            else None
        )
        comm_id = _communication_id(state)

        if upload_success(upload_result):
            meta = _upload_success_metadata(upload_result or {})
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
                            communication_id=comm_id,
                        ),
                        ActivityLogStep(
                            activity_type=ActivityType.SUB_STATUS_CHANGE,
                            to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
                            from_sub_status=StatusSubType.RATECON_STARTED,
                            metadata=meta,
                            communication_id=comm_id,
                        ),
                    ),
                )
            )
            return

        fail_meta = _upload_failure_metadata(upload_result)
        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.EXCEPTION,
                        description=format_ratecon_document_upload_failed_action(),
                        metadata=fail_meta,
                        communication_id=comm_id,
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

        wl_id, tenant_id, run_id = scope
        upload_result = (
            state.data.get("ratecon_s3_upload")
            if isinstance(state.data.get("ratecon_s3_upload"), dict)
            else None
        )
        upload_ok = upload_success(upload_result)
        comm_id = _communication_id(state)
        meta = (
            _upload_success_metadata(upload_result or {})
            if upload_ok
            else _upload_failure_metadata(upload_result)
        )

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=(
                            StatusSubType.DOCUMENT_UPLOADED
                            if upload_ok
                            else StatusSubType.RATECON_STARTED
                        ),
                        from_status=StatusType.PROCESSING,
                        from_sub_status=(
                            StatusSubType.DOCUMENT_UPLOADED
                            if upload_ok
                            else StatusSubType.RATECON_STARTED
                        ),
                        metadata=meta,
                        communication_id=comm_id,
                    ),
                ),
            )
        )
