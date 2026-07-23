"""Appointment scheduling workflow nodes (thin service delegates)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import (
    raise_email_send_error,
    raise_scheduling_result_failure,
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
from app.services.appointment_scheduling.ingress_prepare_service import (
    IngressPrepareService,
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


def prepare_appointment_ingress(state):
    tenant_slug = str(state.data.get("tenant_slug") or state.tenant_slug or "").strip()
    tenant_id = str(state.data.get("tenant_id") or state.tenant_id or "").strip()
    tenant_settings = state.data.get("tenant_settings") or {}
    result = IngressPrepareService().prepare_pickup_changed(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        tenant_settings=tenant_settings,
        payload=state.data,
    )
    if not result.ok:
        state.data["scheduling_prepare_skip_reason"] = result.skip_reason
        logger.info(
            "prepare_appointment_ingress skip reason=%s shipment_id=%s",
            result.skip_reason,
            state.data.get("shipment_id"),
        )
        return state

    state.data["workflow_lifecycle_id"] = result.workflow_lifecycle_id
    state.data["shipments_row_id"] = result.shipments_row_id
    state.data["reference_number"] = result.reference_number
    state.data["customer_name"] = result.customer_name
    if result.customer_contact is not None:
        state.data["customer_contact"] = result.customer_contact.model_dump(mode="json")
    return state


def read_appointment_lifecycle(state):
    LifecycleService().hydrate_read_context(state)
    return state


@safe_node
def run_appointment_intake(state):
    tenant_slug = str(state.data.get("tenant_slug") or "").strip()
    tenant_settings = state.data.get("tenant_settings") or {}
    svc = IntakeService()
    result = svc.run_intake(
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

    state.data.update(svc.build_intake_state_patch(result))
    return state


def compute_appointment_decision(state):
    from app.domain.appointment_scheduling.models import PickupDropoffData

    pickup = PickupDropoffData.model_validate(state.data.get("pickup_dropoff_data") or {})
    decision = DecisionService().compute_decision(
        pickup_dropoff=pickup,
        ascend_context=state.data.get("ascend_context") or {},
        tenant_settings=state.data.get("tenant_settings") or {},
        customer_name=str(state.data.get("customer_name") or ""),
    )
    state.data["llm_scheduling_decision"] = decision.model_dump(mode="json")
    return state


def build_appointment_draft(state):
    draft_result = IntakeService().build_email_draft_from_state(state)
    state.data["email_draft"] = draft_result.email_draft
    state.data["scheduling_payload"] = draft_result.scheduling_payload
    return state


@safe_node
def persist_appointment_draft_ready(state):
    lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    LifecycleService().persist_draft_ready(
        state,
        lifecycle_id=lifecycle_id,
        email_draft=state.data.get("email_draft") or {},
        scheduling_payload=state.data.get("scheduling_payload") or {},
        llm_scheduling_decision=state.data.get("llm_scheduling_decision") or {},
    )
    return state


def notify_appointment_draft_teams(state):
    LifecycleService().finalize_after_teams_notify(state)
    return state


def record_appointment_started(state):
    ActivityService().record_started(state)
    return state


def record_appointment_decision(state):
    ActivityService().record_decision(state)
    return state


def hydrate_appointment_send_context(state):
    LifecycleService().hydrate_appointment_send_context(state)
    return state


@safe_node
def apply_weekend_shifted_pickup(state):
    result = WeekendPickupService().apply_weekend_shifted_pickup_from_state(state)
    state.data["weekend_pickup_result"] = result.to_checkpoint_dict()
    if not result.ok and not result.skipped and result.failure:
        raise result.failure.to_workflow_exception()
    return state


@safe_node
def apply_turvo_delivery_placeholder(state):
    result = TurvoStopUpdateService().apply_delivery_placeholder_from_state(
        state
    )
    state.data["turvo_confirm_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


def finalize_appointment_awaiting_reply(state):
    LifecycleService().finalize_appointment_awaiting_reply(state)
    return state


@safe_node
def send_appointment_draft_email(state):
    result = EmailService().send_draft_from_state(state)
    if not result.sent or not result.communication_id:
        raise_email_send_error(result.error)
    state.data["communication_id"] = result.communication_id
    return state


def classify_appointment_customer_reply(state):
    result = ReplyClassificationService().classify_from_state(state)
    state.data.update(result.to_state_patch())
    return state


@safe_node
def apply_ascend_dropoff_appointment(state):
    result = AscendWriteService().apply_dropoff_from_state(state)
    if not result.ok and result.failure:
        raise result.failure.to_workflow_exception()
    return state


@safe_node
def apply_turvo_delivery_appointment(state):
    result = TurvoStopUpdateService().apply_delivery_from_state(state)
    state.data["turvo_update_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


@safe_node
def send_appointment_confirmation_reply(state):
    result = EmailService().send_confirmation_reply_from_state(state)
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

    result = TurvoStopUpdateService().apply_turvo_tender_from_state(state)
    state.data["turvo_tender_result"] = result.to_checkpoint_dict()
    if not result.ok:
        raise_scheduling_result_failure(result.failure, wire=result.error)
    return state


def record_appointment_reply_completed(state):
    ActivityService().record_reply_completed(state)
    return state


def record_appointment_reply_rejected(state):
    ActivityService().record_reply_rejected(state)
    return state
