"""Node: persist lifecycle + activity log after ``send_tender_email``."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_tender_sent_to_tenant
from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogStep,
    ActivityLogWrite,
)
from app.domain.load_tendering_settings import is_ftl_load_type, resolve_load_type
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.routing_guide_lifecycle_service import RoutingGuideLifecycleService

logger = get_logger(__name__)


def log_tender_activity(state):
    """
    Persist lifecycle + activity log after ``send_tender_email`` (success or failure).

    On success: ``action`` then ``sub_status_change`` (``tender_sent_to_tenant``) in one transaction.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    run_id = str(state.execution_id or "").strip()
    communication_id = str(state.data.get("communication_id") or "").strip() or None

    if not wl_id or not tenant_id:
        logger.warning("log_tender_activity missing workflow_lifecycle_id or tenant_id")
        return state

    activity_log_service = ActivityLogService()
    sent = bool(state.data.get("tender_email_sent"))

    if sent:
        if not run_id:
            logger.warning(
                "log_tender_activity success path skipped: missing execution_id"
            )
            return state

        if is_ftl_load_type(resolve_load_type(state)):
            routing_guide_lifecycle_service = RoutingGuideLifecycleService()
            routing_guide_lifecycle_service.record_tenant_sent(state)
            return state

        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_tender_sent_to_tenant(),
                        communication_id=communication_id,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.TENDER_SENT_TO_TENANT,
                    ),
                ),
            )
        )
    else:
        if not run_id:
            logger.warning(
                "log_tender_activity failure path skipped: missing execution_id"
            )
            return state
        err = state.data.get("tender_email_error") or "tender_email_not_sent"
        activity_log_service.record_status_change(
            ActivityLogWrite(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                to_status=StatusType.FAILED,
                metadata={"error": str(err)},
            )
        )
    return state
