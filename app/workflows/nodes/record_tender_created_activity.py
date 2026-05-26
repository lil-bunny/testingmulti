"""Node: activity logs for tender ingest on the ``tender_created`` workflow run."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_tender_created_action
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService

logger = get_logger(__name__)


def record_tender_created_activity(state):
    """
    Log tender-created action + processing status_change for this lifecycle/run.

    Runs at the start of the ``tender_created`` path after ``workflow_runs`` exists.
    Both rows are written in one transaction via ``record_sequence``.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not tender_id or not run_id:
        logger.warning(
            "record_tender_created_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r tender_id=%r run_id=%r",
            bool(wl_id),
            bool(tenant_id),
            bool(tender_id),
            bool(run_id),
        )
        return state

    row = state.data.get("tender_row")
    order_number = ""
    customer_name = ""
    if isinstance(row, dict):
        order_number = str(row.get("order_number") or "")
        customer_name = str(row.get("customer_name") or row.get("customer_match") or "")

    activity_log_service = ActivityLogService()
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_tender_created_action(
                        tender_id=tender_id,
                        order_number=order_number,
                        customer_name=customer_name,
                    ),
                    metadata={"tender_id": tender_id},
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PROCESSING,
                    to_sub_status=StatusSubType.TENDER_CREATED,
                    from_status=StatusType.NONE,
                    from_sub_status=StatusSubType.NONE,
                    metadata={"tender_id": tender_id},
                ),
            ),
        )
    )
    return state
