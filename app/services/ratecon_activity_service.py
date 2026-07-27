"""Ratecon workflow activity logging (received, processed)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_ratecon_page_count_cached_action,
    format_ratecon_page_count_failed_action,
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


def page_count_cache_success(cache_result: dict[str, Any] | None) -> bool:
    if not isinstance(cache_result, dict):
        return False
    if cache_result.get("skipped"):
        return False
    if not cache_result.get("success"):
        return False
    page_count = cache_result.get("page_count")
    try:
        return int(page_count) >= 1
    except (TypeError, ValueError):
        return False


def _cache_failure_metadata(cache_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cache_result, dict):
        return {"reason": "missing_ratecon_page_count_cache"}
    meta: dict[str, Any] = {"ratecon_page_count_cache": cache_result}
    reason = cache_result.get("reason")
    if reason is not None and str(reason).strip():
        meta["reason"] = str(reason).strip()
        return meta
    for item in cache_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        err = item.get("error_message")
        if err is not None and str(err).strip():
            meta["reason"] = str(err).strip()
            return meta
    meta["reason"] = "ratecon_page_count_not_cached"
    return meta


def _cache_success_metadata(cache_result: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    page_count = cache_result.get("page_count")
    if page_count is not None:
        meta["page_count"] = page_count
    persist = cache_result.get("document_analysis")
    if isinstance(persist, dict):
        doc_id = persist.get("id")
        if doc_id is not None and str(doc_id).strip():
            meta["document_analysis_id"] = str(doc_id).strip()
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

    def record_processed(self, state: WorkflowState) -> None:
        """
        Terminal ratecon activity: always COMPLETED / RATECON_STARTED.

        Success caches page count (action log). Failure/skip logs an exception
        row, then still completes so driver_assignment can enqueue.
        """
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
        cache_result = (
            state.data.get("ratecon_page_count_cache")
            if isinstance(state.data.get("ratecon_page_count_cache"), dict)
            else None
        )
        cache_ok = page_count_cache_success(cache_result)
        comm_id = _communication_id(state)

        if cache_ok:
            meta = _cache_success_metadata(cache_result or {})
            first_step = ActivityLogStep(
                activity_type=ActivityType.ACTION,
                description=format_ratecon_page_count_cached_action(),
                metadata=meta,
                communication_id=comm_id,
            )
        else:
            fail_meta = _cache_failure_metadata(cache_result)
            first_step = ActivityLogStep(
                activity_type=ActivityType.EXCEPTION,
                description=format_ratecon_page_count_failed_action(),
                metadata=fail_meta,
                communication_id=comm_id,
            )
            meta = fail_meta

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    first_step,
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.RATECON_STARTED,
                        from_status=StatusType.PROCESSING,
                        from_sub_status=StatusSubType.RATECON_STARTED,
                        metadata=meta,
                        communication_id=comm_id,
                    ),
                ),
            )
        )
