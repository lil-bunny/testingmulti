"""Appointment scheduling workflow nodes (thin service delegates)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import (
    raise_email_send_error,
    raise_scheduling_result_failure,
)
from app.domain.appointment_scheduling.constants import (
    APPOINTMENT_PAYLOAD,
    LLM_APPOINTMENT_DECISION,
)
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)
from app.services.appointment_scheduling.ascend_write_service import (
    AscendWriteService,
)
from app.services.appointment_scheduling.decision_service import (
    DecisionService,
)
from app.services.appointment_scheduling.email_service import (
    EmailService,
)
from app.services.appointment_scheduling.intake_service import (
    IntakeService,
)
from app.services.appointment_scheduling.lifecycle_service import (
    LifecycleService,
)
from app.services.appointment_scheduling.reply_classification_service import (
    ReplyClassificationService,
)
from app.services.appointment_scheduling.turvo_stop_update_service import (
    TurvoStopUpdateService,
)
from app.services.appointment_scheduling.weekend_pickup_service import (
    WeekendPickupService,
)
from app.workflows.utils.decorators import safe_node

logger = get_logger(__name__)


def read_appointment_lifecycle(state):
    lifecycle = LifecycleService()
    lifecycle.hydrate_read_context(state)
    return state


@safe_node
def run_appointment_intake(state):
    tenant_slug = str(state.data.get("tenant_slug") or "").strip()
    tenant_settings = state.data.get("tenant_settings") or {}
    intake = IntakeService()
    result = intake.run_intake(
        tenant_slug=tenant_slug,
        tenant_settings=tenant_settings,
        payload=state.data,
    )
    if not result.ok:
        logger.info(
            "run_appointment_intake failed code=%s lifecycle_id=%s",
            result.failure.code if result.failure else None,
            state.data.get("workflow_lifecycle_id"),
        )
        raise_scheduling_result_failure(result.failure)

    state.data.update(intake.build_intake_state_patch(result))
    return state


def compute_appointment_decision(state):
    from app.domain.appointment_scheduling.models import PickupDropoffData

    pickup = PickupDropoffData.model_validate(state.data.get("pickup_dropoff_data") or {})
    decision_svc = DecisionService()
    decision = decision_svc.compute_decision(
        pickup_dropoff=pickup,
        ascend_context=state.data.get("ascend_context") or {},
        tenant_settings=state.data.get("tenant_settings") or {},
        customer_name=str(state.data.get("customer_name") or ""),
    )
    state.data[LLM_APPOINTMENT_DECISION] = decision.model_dump(mode="json")
    return state


def build_appointment_draft(state):
    intake = IntakeService()
    draft_result = intake.build_email_draft_from_state(state)
    state.data["email_draft"] = draft_result.email_draft
    state.data[APPOINTMENT_PAYLOAD] = draft_result.appointment_payload
    return state


@safe_node
def persist_appointment_draft_ready(state):
    lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    lifecycle = LifecycleService()
    lifecycle.persist_draft_ready(
        state,
        lifecycle_id=lifecycle_id,
        email_draft=state.data.get("email_draft") or {},
        appointment_payload=state.data.get(APPOINTMENT_PAYLOAD) or {},
        llm_appointment_decision=state.data.get(LLM_APPOINTMENT_DECISION) or {},
    )
    return state


def notify_appointment_draft_teams(state):
    lifecycle = LifecycleService()
    lifecycle.finalize_after_teams_notify(state)
    return state


def record_appointment_started(state):
    activity = ActivityService()
    activity.record_started(state)
    return state


def record_appointment_decision(state):
    activity = ActivityService()
    activity.record_decision(state)
    return state


def hydrate_appointment_send_context(state):
    lifecycle = LifecycleService()
    lifecycle.hydrate_appointment_send_context(state)
    return state


@safe_node
def apply_weekend_shifted_pickup(state):
    weekend = WeekendPickupService()
    result = weekend.apply_weekend_shifted_pickup_from_state(state)
    state.data["weekend_pickup_result"] = result.to_checkpoint_dict()
    if not result.ok and not result.skipped and result.failure:
        raise result.failure.to_workflow_exception()
    return state


@safe_node
def apply_turvo_delivery_placeholder(state):
    turvo = TurvoStopUpdateService()
    result = turvo.apply_delivery_placeholder_from_state(state)
    state.data["turvo_confirm_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


def finalize_appointment_awaiting_reply(state):
    lifecycle = LifecycleService()
    lifecycle.finalize_appointment_awaiting_reply(state)
    return state


@safe_node
def send_appointment_draft_email(state):
    email = EmailService()
    result = email.send_draft_from_state(state)
    if not result.sent or not result.communication_id:
        raise_email_send_error(result.error)
    state.data["communication_id"] = result.communication_id
    return state


def classify_appointment_customer_reply(state):
    reply = ReplyClassificationService()
    result = reply.classify_from_state(state)
    state.data.update(result.to_state_patch())
    return state


@safe_node
def apply_ascend_dropoff_appointment(state):
    ascend = AscendWriteService()
    result = ascend.apply_dropoff_from_state(state)
    if not result.ok and result.failure:
        raise result.failure.to_workflow_exception()
    return state


@safe_node
def apply_turvo_delivery_appointment(state):
    turvo = TurvoStopUpdateService()
    result = turvo.apply_delivery_from_state(state)
    state.data["turvo_update_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


@safe_node
def send_appointment_confirmation_reply(state):
    email = EmailService()
    result = email.send_confirmation_reply_from_state(state)
    state.data["confirmation_sent"] = result.sent
    if result.communication_id:
        state.data["confirmation_communication_id"] = result.communication_id
    if not result.sent:
        raise_email_send_error(result.error)
    return state


@safe_node
def apply_turvo_tender_status(state):
    if not state.data.get("confirmation_sent"):
        return state

    turvo = TurvoStopUpdateService()
    result = turvo.apply_turvo_tender_from_state(state)
    state.data["turvo_tender_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


def record_appointment_reply_completed(state):
    activity = ActivityService()
    activity.record_reply_completed(state)
    return state


def record_appointment_reply_rejected(state):
    activity = ActivityService()
    activity.record_reply_rejected(state)
    return state
