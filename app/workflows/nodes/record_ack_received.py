"""Nodes: classify carrier ack reply (LLM), then finalize lifecycle by decision."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_carrier_ack_llm_action
from app.domain.activity_log_write import ActivityLogWrite
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.communications.service import CommunicationsService
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.tools.carrier_ack import (
    classify_carrier_acknowledgment,
    normalize_carrier_reply_body,
)
from app.utils.prompts import carrier_ack_system_prompt

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
    """LLM gate: classify using full email thread from ``communications`` when available."""
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    thread_id = str(state.data.get("thread_id") or "").strip()
    fallback_body = state.data.get("body")

    latest_reply = normalize_carrier_reply_body(body=fallback_body)

    reply_text = latest_reply
    thread_message_count = 0
    if tenant_id and thread_id:
        communications_service = CommunicationsService()
        reply_text, thread_message_count = (
            communications_service.build_thread_llm_user_message(
                tenant_id,
                thread_id,
                fallback_body=fallback_body,
            )
        )

    state.data["carrier_ack_normalized_reply"] = latest_reply
    state.data["carrier_ack_thread_llm_input"] = reply_text
    state.data["carrier_ack_thread_message_count"] = thread_message_count
    result = classify_carrier_acknowledgment(
        reply_text,
        system_prompt=carrier_ack_system_prompt,
    )
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
    tender_id = str(state.data.get("tender_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip()
    if wl_id and tenant_id and tender_id and run_id:
        try:
            confidence = float(result.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        activity_log_service = ActivityLogService()
        activity_log_id = activity_log_service.record_action(
            ActivityLogWrite(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                description=format_carrier_ack_llm_action(
                    decision=decision,
                    reason=state.data["carrier_ack_reason"],
                    confidence=confidence,
                ),
                metadata={
                    "source": "classify_carrier_ack",
                    "tender_id": tender_id,
                    "carrier_ack_decision": decision,
                    "user_input": reply_text,
                    "output": result,
                },
            )
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
