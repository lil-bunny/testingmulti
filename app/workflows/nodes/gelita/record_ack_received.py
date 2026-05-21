"""Nodes: classify carrier ack reply (LLM), then record completion."""

from __future__ import annotations

from app.core.logger import get_logger
from app.tools.gelita.email_parser import (
    classify_carrier_acknowledgment,
    normalize_carrier_reply_body,
)
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.workflows.nodes.gelita.load_tendering_helpers import (
    status_type_from_db,
    sub_status_type_from_db,
)

logger = get_logger(__name__)


def classify_carrier_ack(state):
    """LLM gate: set ``carrier_ack_confirmed`` from plain reply body (Unipile webhook fields)."""
    reply_text = normalize_carrier_reply_body(
        body=state.data.get("body"),
        body_plain=state.data.get("body_plain"),
    )
    result = classify_carrier_acknowledgment(reply_text)
    state.data["carrier_ack_confirmed"] = bool(result.get("is_acknowledgment"))
    state.data["carrier_ack_reason"] = str(result.get("reason") or "")
    state.data["carrier_ack_llm"] = result
    logger.info(
        "classify_carrier_ack tender_id=%s confirmed=%s reason=%s",
        state.data.get("tender_id"),
        state.data["carrier_ack_confirmed"],
        state.data["carrier_ack_reason"],
    )
    return state


def record_ack_received(state):
    """
    Carrier ack validated: mark lifecycle complete, append activity log.
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

    lifecycle_svc.update_lifecycle_status(
        lifecycle_id=wl_id,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.ACCEPTED,
    )

    try:
        ActivityLogService().record_activity(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=str(state.execution_id),
            activity_type=ActivityType.STATUS_CHANGE,
            description="Carrier acknowledgment recorded; tender marked complete",
            from_status=prev_status,
            to_status=StatusType.COMPLETED,
            from_sub_status=prev_sub,
            to_sub_status=StatusSubType.ACCEPTED,
            actor_type=ActorType.SYSTEM,
            metadata={"tender_id": tender_id},
        )
    except Exception:
        logger.exception(
            "record_ack_received activity log failed lifecycle_id=%s",
            wl_id,
        )

    state.data["ack_recorded"] = True
    state.data["tender_status"] = StatusType.COMPLETED.value
    return state
