"""Node: persist lifecycle + activity log after ``send_tender_email``."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.workflows.nodes.gelita.load_tendering_helpers import (
    status_type_from_db,
    sub_status_type_from_db,
)

logger = get_logger(__name__)


def log_tender_activity(state):
    """
    Persist lifecycle + activity log after ``send_tender_email`` (success or failure).
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    if not wl_id or not tenant_id:
        logger.warning("log_tender_activity missing workflow_lifecycle_id or tenant_id")
        return state

    lifecycle_svc = WorkflowLifecycleService()
    prev = lifecycle_svc.read_lifecycle_row_by_id(wl_id)
    prev_status = status_type_from_db((prev or {}).get("status"))
    prev_sub = sub_status_type_from_db((prev or {}).get("sub_status"))
    activity_log_svc = ActivityLogService()

    sent = bool(state.data.get("tender_email_sent"))
    if sent:
        lifecycle_svc.update_lifecycle_status(
            lifecycle_id=wl_id,
            status=StatusType.PROCESSING,
            sub_status=StatusSubType.TENDER_SENT,
        )
        activity_log_svc.insert(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=str(state.execution_id),
            activity_type="tender_email_sent",
            message="Tender email sent to vendor",
            from_status=prev_status,
            to_status=StatusType.PROCESSING,
            from_sub_status=prev_sub,
            to_sub_status=StatusSubType.TENDER_SENT,
        )
    else:
        err = state.data.get("tender_email_error") or "tender_email_not_sent"
        lifecycle_svc.update_lifecycle_status(
            lifecycle_id=wl_id,
            status=StatusType.PROCESSING,
            sub_status=StatusSubType.TENDER_EMAIL_FAILED,
        )
        activity_log_svc.insert(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=str(state.execution_id),
            activity_type="tender_email_failed",
            message=str(err),
            from_status=prev_status,
            to_status=StatusType.PROCESSING,
            from_sub_status=prev_sub,
            to_sub_status=StatusSubType.TENDER_EMAIL_FAILED,
            payload={"error": str(err)},
        )
    return state
