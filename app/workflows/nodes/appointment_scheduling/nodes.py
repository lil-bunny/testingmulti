"""Appointment scheduling workflow nodes (thin service delegates)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.services.appointment_scheduling.decision_service import (
    AppointmentSchedulingDecisionService,
)
from app.services.appointment_scheduling.draft_service import AppointmentSchedulingDraftService
from app.services.appointment_scheduling.intake_service import AppointmentSchedulingIntakeService
from app.services.appointment_scheduling.lifecycle_service import (
    AppointmentSchedulingLifecycleService,
)
from app.services.appointment_scheduling.activity_service import (
    AppointmentSchedulingActivityService,
)
from app.services.appointment_scheduling.email_service import (
    AppointmentSchedulingEmailService,
)
from app.services.appointment_scheduling.reply_classification_service import (
    AppointmentReplyClassificationService,
)
from app.services.appointment_scheduling.ascend_write_service import (
    AppointmentSchedulingAscendWriteService,
)
from app.services.appointment_scheduling.turvo_write_service import (
    AppointmentSchedulingTurvoWriteService,
)
from app.services.appointment_scheduling.weekend_pickup_service import (
    AppointmentSchedulingWeekendPickupService,
)
from app.services.appointment_scheduling.turvo_confirm_service import (
    AppointmentSchedulingTurvoConfirmService,
)
from app.services.appointment_scheduling.confirmation_email_service import (
    AppointmentSchedulingConfirmationEmailService,
)
from app.services.shipment_location_link_service import ShipmentLocationLinkService

logger = get_logger(__name__)


def read_appointment_scheduling_lifecycle(state):
    lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    row = AppointmentSchedulingLifecycleService().load_context(lifecycle_id)
    state.data["workflow_lifecycle_row"] = row or {}
    if row and row.get("metadata"):
        state.data["workflow_lifecycle_metadata"] = row.get("metadata")
    return state


def run_scheduling_intake(state):
    tenant_slug = str(state.data.get("tenant_slug") or "").strip()
    tenant_settings = state.data.get("tenant_settings") or {}
    result = AppointmentSchedulingIntakeService().run_intake(
        tenant_slug=tenant_slug,
        tenant_settings=tenant_settings,
        payload=state.data,
    )
    if not result.ok:
        state.data["scheduling_intake_skip_reason"] = result.skip_reason
        lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        if lifecycle_id:
            AppointmentSchedulingLifecycleService().mark_failed(
                lifecycle_id,
                result.skip_reason or "intake_failed",
                tenant_id=(state.tenant_id or state.data.get("tenant_id") or "").strip() or None,
                workflow_run_id=str(state.execution_id or "").strip() or None,
            )
        logger.info(
            "run_scheduling_intake skip reason=%s lifecycle_id=%s",
            result.skip_reason,
            lifecycle_id,
        )
        return state

    state.data["shipment"] = result.shipment
    state.data["ascend_shipment"] = result.ascend_shipment
    state.data["customer_contact"] = (
        result.customer_contact.model_dump(mode="json") if result.customer_contact else None
    )
    state.data["pickup_dropoff_data"] = (
        result.pickup_dropoff_data.model_dump(mode="json")
        if result.pickup_dropoff_data
        else None
    )
    state.data["draft_static"] = (
        result.draft_static.model_dump(mode="json") if result.draft_static else None
    )
    state.data["customer_name"] = result.customer_name
    state.data["customer_id"] = result.customer_id
    state.data["reference_number"] = result.reference_number
    state.data["ascend_context"] = {
        "office_code": result.office_code,
        "access_token": result.ascend_access_token,
        "appointments": result.ascend_appointments,
    }
    shipments_row_id = str(state.data.get("shipments_row_id") or "").strip()
    if shipments_row_id and isinstance(result.shipment, dict):
        link_result = ShipmentLocationLinkService().try_link_from_turvo_shipment_payload(
            result.shipment,
            shipments_row_id=shipments_row_id,
        )
        if link_result is not None:
            state.data["shipment_location_link"] = {
                "success": True,
                "pickup_location_id": link_result.pickup_location_id,
                "delivery_location_id": link_result.delivery_location_id,
            }
    return state


def compute_scheduling_decision(state):
    from app.domain.appointment_scheduling.models import PickupDropoffData

    pickup = PickupDropoffData.model_validate(state.data.get("pickup_dropoff_data") or {})
    contact = state.data.get("customer_contact") or {}
    decision = AppointmentSchedulingDecisionService().compute_decision(
        pickup_dropoff=pickup,
        ascend_context=state.data.get("ascend_context") or {},
        tenant_settings=state.data.get("tenant_settings") or {},
        customer_name=str(state.data.get("customer_name") or ""),
        customer_contact_transit_time=str(contact.get("transit_time") or ""),
    )
    state.data["llm_scheduling_decision"] = decision.model_dump(mode="json")
    return state


def build_email_scheduling_draft(state):
    from app.domain.appointment_scheduling.models import (
        DraftStatic,
        LlmSchedulingDecision,
        PickupDropoffData,
    )

    contact = state.data.get("customer_contact") or {}
    draft_result = AppointmentSchedulingDraftService().build_email_draft(
        pickup_dropoff=PickupDropoffData.model_validate(
            state.data.get("pickup_dropoff_data") or {}
        ),
        llm_decision=LlmSchedulingDecision.model_validate(
            state.data.get("llm_scheduling_decision") or {}
        ),
        draft_static=DraftStatic.model_validate(state.data.get("draft_static") or {}),
        to_email=str(contact.get("email") or ""),
        tenant_settings=state.data.get("tenant_settings") or {},
        load_id=str(state.data.get("load_id") or ""),
        customer_name=str(state.data.get("customer_name") or ""),
    )
    state.data["email_draft"] = draft_result.email_draft
    state.data["scheduling_payload"] = draft_result.scheduling_payload
    return state


def persist_scheduling_draft_ready(state):
    lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    AppointmentSchedulingLifecycleService().persist_draft_ready(
        state,
        lifecycle_id=lifecycle_id,
        email_draft=state.data.get("email_draft") or {},
        scheduling_payload=state.data.get("scheduling_payload") or {},
        llm_scheduling_decision=state.data.get("llm_scheduling_decision") or {},
    )
    return state


def record_appointment_scheduling_started(state):
    AppointmentSchedulingActivityService().record_started(state)
    return state


def record_scheduling_decision(state):
    AppointmentSchedulingActivityService().record_decision(state)
    return state


def hydrate_appointment_confirm_context(state):
    AppointmentSchedulingLifecycleService().hydrate_confirm_context(state)
    return state


def apply_weekend_shifted_pickup(state):
    result = AppointmentSchedulingWeekendPickupService().apply_from_state(state)
    state.data["weekend_pickup_result"] = {
        "ok": result.ok,
        "skipped": result.skipped,
        "dry_run": result.dry_run,
        "error": result.error,
        "ascend_updated": result.ascend_updated,
        "turvo_updated": result.turvo_updated,
        "turvo_pickup_start_time": result.turvo_pickup_start_time,
        "pickup_stop_name": result.pickup_stop_name,
        "ascend_response": result.ascend_response,
        "turvo_response": result.turvo_response,
    }
    AppointmentSchedulingActivityService().record_weekend_pickup_update(
        state,
        result=state.data["weekend_pickup_result"],
    )
    if not result.ok and not result.skipped:
        raise RuntimeError(result.error or "weekend_pickup_update_failed")
    return state


def apply_turvo_delivery_placeholder(state):
    import asyncio

    result = asyncio.run(
        AppointmentSchedulingTurvoConfirmService().apply_delivery_placeholder_from_state(state)
    )
    state.data["turvo_confirm_result"] = {
        "ok": result.ok,
        "updated": result.updated,
        "error": result.error,
        "stop_name": result.stop_name,
        "start_time": result.start_time,
        "response": result.response,
    }
    AppointmentSchedulingActivityService().record_turvo_confirm_placeholder(
        state,
        result=state.data["turvo_confirm_result"],
    )
    if not result.ok:
        raise RuntimeError(result.error or "turvo_delivery_placeholder_failed")
    return state


def finalize_confirm_awaiting_reply(state):
    actor_id = str(state.data.get("actor_user_id") or "").strip() or None
    communication_id = str(state.data.get("communication_id") or "").strip() or None
    AppointmentSchedulingActivityService().finalize_confirm_awaiting_reply(
        state,
        communication_id=communication_id,
        actor_id=actor_id,
    )
    return state


def send_appointment_scheduling_email(state):
    result = AppointmentSchedulingEmailService().send_from_state(state)
    if not result.sent or not result.communication_id:
        raise RuntimeError(result.error or "appointment_draft_send_failed")
    state.data["communication_id"] = result.communication_id
    return state


def record_appointment_email_sent(state):
    actor_id = str(state.data.get("actor_user_id") or "").strip() or None
    communication_id = str(state.data.get("communication_id") or "").strip()
    AppointmentSchedulingActivityService().record_email_sent(
        state,
        communication_id=communication_id,
        actor_id=actor_id,
    )
    return state


def classify_appointment_customer_reply(state):
    result = AppointmentReplyClassificationService().classify_from_state(state)
    state.data.update(result.to_state_patch())
    return state


def apply_ascend_dropoff_appointment(state):
    result = AppointmentSchedulingAscendWriteService().apply_dropoff_from_state(state)
    state.data["ascend_update_result"] = {
        "ok": result.ok,
        "skipped": result.skipped,
        "dry_run": result.dry_run,
        "error": result.error,
        "payload": result.payload,
        "response": result.response,
    }
    AppointmentSchedulingActivityService().record_ascend_update(state)
    if not result.ok:
        raise RuntimeError(result.error or "ascend_dropoff_update_failed")
    return state


def apply_turvo_delivery_appointment(state):
    import asyncio

    result = asyncio.run(
        AppointmentSchedulingTurvoWriteService().apply_delivery_from_state(state)
    )
    state.data["turvo_update_result"] = {
        "ok": result.ok,
        "updated": result.updated,
        "error": result.error,
        "stop_name": result.stop_name,
        "start_time": result.start_time,
        "response": result.response,
    }
    AppointmentSchedulingActivityService().record_turvo_update(state)
    if not result.ok:
        raise RuntimeError(result.error or "turvo_delivery_update_failed")
    return state


def send_appointment_confirmation_reply(state):
    result = AppointmentSchedulingConfirmationEmailService().send_from_state(state)
    state.data["confirmation_sent"] = result.sent
    if result.communication_id:
        state.data["confirmation_communication_id"] = result.communication_id
    if result.error:
        state.data["confirmation_error"] = result.error
    if result.sent:
        AppointmentSchedulingActivityService().record_confirmation_sent(state)
    return state


def record_appointment_reply_completed(state):
    lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    confirmed_at = str(state.data.get("confirmed_delivery_at") or "").strip() or None
    AppointmentSchedulingActivityService().record_reply_completed(state)
    if lifecycle_id:
        AppointmentSchedulingLifecycleService().mark_completed(
            lifecycle_id,
            confirmed_delivery_at=confirmed_at,
        )
    return state
