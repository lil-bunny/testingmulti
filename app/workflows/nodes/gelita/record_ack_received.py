"""Nodes: classify carrier ack reply (LLM), then finalize lifecycle by decision."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.tools.gelita.email_parser import (
    classify_carrier_acknowledgment,
    normalize_carrier_reply_body,
)

logger = get_logger(__name__)

_ACK_DESCRIPTIONS: dict[str, str] = {
    StatusSubType.ACCEPTED.value: (
        "Carrier acknowledgment recorded; tender marked complete"
    ),
    StatusSubType.REJECTED.value: (
        "Carrier declined the tender; lifecycle marked complete"
    ),
}


def classify_carrier_ack(state):
    """LLM gate: set ``carrier_ack_decision`` from plain reply body (Unipile webhook fields)."""
    reply_text = normalize_carrier_reply_body(
        body=state.data.get("body"),
        body_plain=state.data.get("body_plain"),
    )
    state.data["carrier_ack_normalized_reply"] = reply_text
    result = classify_carrier_acknowledgment(reply_text)
    decision = str(result.get("decision") or StatusSubType.DO_NOTHING.value)
    state.data["carrier_ack_decision"] = decision
    state.data["carrier_ack_reason"] = str(result.get("reason") or "")
    state.data["carrier_ack_llm"] = result
    logger.info(
        "classify_carrier_ack tender_id=%s decision=%s reason=%s",
        state.data.get("tender_id"),
        decision,
        state.data["carrier_ack_reason"],
    )

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip()
    if wl_id and tenant_id and tender_id and run_id:
        try:
            confidence = float(result.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        activity_log_service = ActivityLogService()
        activity_log_id = activity_log_service.record_carrier_ack_llm_action(
            tenant_id=tenant_id,
            tender_id=tender_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            decision=decision,
            reason=state.data["carrier_ack_reason"],
            confidence=confidence,
            user_input=reply_text,
            llm_output=result,
        )
        if activity_log_id:
            state.data["carrier_ack_llm_activity_log_id"] = activity_log_id
    else:
        logger.warning(
            "classify_carrier_ack skipped LLM action activity log "
            "wl_id=%r tenant_id=%r tender_id=%r run_id=%r",
            bool(wl_id),
            bool(tenant_id),
            bool(tender_id),
            bool(run_id),
        )

    return state


def record_ack_received(state):
    """
    Apply carrier ack outcome: complete lifecycle with sub_status from LLM decision.

    - ``accepted`` / ``rejected``: lifecycle + status_change activity log (transactional).
    - ``do_nothing``: lifecycle only (no status_change log; LLM action logged in ``classify_carrier_ack``).
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    decision = str(
        state.data.get("carrier_ack_decision") or StatusSubType.DO_NOTHING.value
    ).strip()

    if not wl_id or not tenant_id or not tender_id:
        logger.warning(
            "record_ack_received missing workflow_lifecycle_id, tender_id, or tenant_id"
        )
        return state

    if decision not in (
        StatusSubType.ACCEPTED.value,
        StatusSubType.REJECTED.value,
        StatusSubType.DO_NOTHING.value,
    ):
        logger.warning(
            "record_ack_received unknown carrier_ack_decision=%r tender_id=%s",
            decision,
            tender_id,
        )
        decision = StatusSubType.DO_NOTHING.value

    to_sub = StatusSubType(decision)
    record_activity = decision != StatusSubType.DO_NOTHING.value
    description = _ACK_DESCRIPTIONS.get(decision)

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_status=StatusType.COMPLETED,
        to_sub_status=to_sub,
        activity_type=ActivityType.STATUS_CHANGE,
        description=description,
        actor_type=ActorType.SYSTEM,
        metadata={"tender_id": tender_id, "carrier_ack_decision": decision},
        record_activity=record_activity,
    )

    state.data["ack_recorded"] = True
    state.data["tender_status"] = StatusType.COMPLETED.value
    state.data["carrier_ack_final_sub_status"] = decision
    return state
