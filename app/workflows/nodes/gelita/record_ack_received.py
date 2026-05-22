"""Nodes: classify carrier ack reply (LLM), then record completion."""

from __future__ import annotations

from app.core.logger import get_logger
from app.tools.gelita.email_parser import (
    classify_carrier_acknowledgment,
    normalize_carrier_reply_body,
)
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService

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

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_status=StatusType.COMPLETED,
        to_sub_status=StatusSubType.ACCEPTED,
        activity_type=ActivityType.STATUS_CHANGE,
        description="Carrier acknowledgment recorded; tender marked complete",
        actor_type=ActorType.SYSTEM,
        metadata={"tender_id": tender_id},
    )

    state.data["ack_recorded"] = True
    state.data["tender_status"] = StatusType.COMPLETED.value
    return state
