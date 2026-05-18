"""Node: carrier ack validated — complete tender + lifecycle, activity log."""

from __future__ import annotations

from app.core import logger
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.workflows.nodes.gelita.load_tendering_helpers import (
    status_type_from_db,
    sub_status_type_from_db,
)


def record_ack_received(state):
    """
    Carrier ack validated: mark tender + lifecycle complete, append activity log.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()

    if not wl_id or not tenant_id or not tender_id:
        logger.warning(
            "record_ack_received missing workflow_lifecycle_id, tender_id, or tenant_id"
        )
        return state

    lifecycle_svc = WorkflowLifecycleService()
    prev = lifecycle_svc.read_lifecycle_row_by_id(wl_id)
    if not prev:
        logger.warning("record_ack_received lifecycle not found id=%s", wl_id)
        return state

    prev_status = status_type_from_db(prev.get("status"))
    prev_sub = sub_status_type_from_db(prev.get("sub_status"))

    tender_svc = TenderService()
    tender_updated = tender_svc.update_row_status(
        tenant_id=tenant_id,
        tender_id=tender_id,
        status=StatusType.COMPLETED,
    )
    if not tender_updated:
        logger.warning(
            "record_ack_received tender update skipped or failed tender_id=%s",
            tender_id,
        )

    lifecycle_svc.update_lifecycle_status(
        lifecycle_id=wl_id,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.ACCEPTED,
    )

    try:
        ActivityLogService().insert(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=str(state.execution_id),
            activity_type="ack_received",
            message="Carrier acknowledgment recorded; tender marked complete",
            from_status=prev_status,
            to_status=StatusType.COMPLETED.value,
            from_sub_status=prev_sub,
            to_sub_status=StatusSubType.ACCEPTED,
            payload={"tender_id": tender_id, "tender_row_updated": tender_updated},
        )
    except Exception:
        logger.exception(
            "record_ack_received activity log failed lifecycle_id=%s",
            wl_id,
        )

    state.data["ack_recorded"] = True
    state.data["tender_status"] = StatusType.COMPLETED.value
    return state
