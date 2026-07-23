"""Appointment scheduling lifecycle metadata and checkpoint keys."""

from __future__ import annotations

EMAIL_DRAFT = "email_draft"
DRAFT_SEND_QUEUED = "draft_send_queued"
APPOINTMENT_PAYLOAD = "appointment_payload"
LLM_APPOINTMENT_DECISION = "llm_appointment_decision"
APPOINTMENT_FAILURE_REASON = "appointment_failure_reason"
APPOINTMENT_INGRESS_SKIP_REASON = "appointment_ingress_skip_reason"
APPOINTMENT_INTAKE_SKIP_REASON = "appointment_intake_skip_reason"

LEGACY_STATE_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    APPOINTMENT_PAYLOAD: ("scheduling_payload",),
    LLM_APPOINTMENT_DECISION: ("llm_scheduling_decision",),
    APPOINTMENT_INGRESS_SKIP_REASON: ("scheduling_prepare_skip_reason",),
    APPOINTMENT_INTAKE_SKIP_REASON: ("scheduling_intake_skip_reason",),
    APPOINTMENT_FAILURE_REASON: ("scheduling_failure_reason",),
}
