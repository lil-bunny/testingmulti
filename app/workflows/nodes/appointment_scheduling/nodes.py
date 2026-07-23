"""Appointment scheduling workflow nodes (thin service delegates)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.error_catalog import IntegrationError
from app.exceptions import WorkflowException
from app.services.appointment_scheduling.decision_service import (
    AppointmentSchedulingDecisionService,
)
from app.services.appointment_scheduling.draft_service import AppointmentSchedulingDraftService
from app.services.appointment_scheduling.intake_service import AppointmentSchedulingIntakeService
from app.services.appointment_scheduling.ingress_prepare_service import (
    AppointmentSchedulingIngressPrepareService,
)
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
from app.services.appointment_scheduling.teams_notification_service import (
    AppointmentSchedulingTeamsNotificationService,
)
from app.services.shipment_location_link_service import ShipmentLocationLinkService
from app.workflows.utils.decorators import safe_node

logger = get_logger(__name__)


def prepare_scheduling_ingress(state):
    tenant_slug = str(state.data.get("tenant_slug") or state.tenant_slug or "").strip()
    tenant_id = str(state.data.get("tenant_id") or state.tenant_id or "").strip()
    tenant_settings = state.data.get("tenant_settings") or {}
    result = AppointmentSchedulingIngressPrepareService().prepare_pickup_changed(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        tenant_settings=tenant_settings,
        payload=state.data,
    )
    if not result.ok:
        state.data["scheduling_prepare_skip_reason"] = result.skip_reason
        logger.info(
            "prepare_scheduling_ingress skip reason=%s shipment_id=%s",
            result.skip_reason,
            state.data.get("shipment_id"),
        )
        return state

    state.data["workflow_lifecycle_id"] = result.workflow_lifecycle_id
    state.data["shipments_row_id"] = result.shipments_row_id
    state.data["reference_number"] = result.reference_number
    state.data["shipment"] = result.shipment
    state.data["customer_name"] = result.customer_name
    if result.customer_contact is not None:
        state.data["customer_contact"] = result.customer_contact.model_dump(mode="json")
    return state


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
        failure = result.failure
        lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        if failure and lifecycle_id:
            state.data["scheduling_intake_skip_reason"] = failure.code
            AppointmentSchedulingLifecycleService().mark_failed(
                lifecycle_id,
                failure,
                tenant_id=(state.tenant_id or state.data.get("tenant_id") or "").strip() or None,
                workflow_run_id=str(state.execution_id or "").strip() or None,
            )
        logger.info(
            "run_scheduling_intake skip code=%s lifecycle_id=%s",
            failure.code if failure else None,
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
    decision = AppointmentSchedulingDecisionService().compute_decision(
        pickup_dropoff=pickup,
        ascend_context=state.data.get("ascend_context") or {},
        tenant_settings=state.data.get("tenant_settings") or {},
        customer_name=str(state.data.get("customer_name") or ""),
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


def notify_appointment_scheduling_draft_teams(state):
    result = AppointmentSchedulingTeamsNotificationService().notify_from_state(state)
    state.data["appointment_scheduling_teams_notification_sent"] = result.sent
    if result.skip_reason:
        state.data["appointment_scheduling_teams_notification_skipped"] = result.skip_reason
    if result.error:
        state.data["appointment_scheduling_teams_notification_error"] = result.error
    AppointmentSchedulingActivityService().record_draft_pending_review(state)
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


@safe_node
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
    if not result.ok and not result.skipped and result.failure:
        raise WorkflowException(result.failure.code, result.failure.message)
    return state


@safe_node
def apply_turvo_delivery_placeholder(state):
    result = AppointmentSchedulingTurvoConfirmService().apply_delivery_placeholder_from_state(state)
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
        raise WorkflowException(
            IntegrationError.VENDOR_API_ERROR,
            result.error or IntegrationError.VENDOR_API_ERROR.description,
        )
    return state


def finalize_confirm_awaiting_reply(state):
    actor_id = str(state.data.get("actor_user_id") or "").strip() or None
    communication_id = str(state.data.get("communication_id") or "").strip() or None
    svc = AppointmentSchedulingActivityService()
    svc.record_confirm_email_sent(
        state,
        communication_id=communication_id,
        actor_id=actor_id,
    )
    svc.record_awaiting_customer_reply(state)
    return state


@safe_node
def send_appointment_scheduling_email(state):
    result = AppointmentSchedulingEmailService().send_from_state(state)
    if not result.sent or not result.communication_id:
        raise WorkflowException(
            IntegrationError.EMAIL_SEND_FAILED,
            result.error or IntegrationError.EMAIL_SEND_FAILED.description,
        )
    state.data["communication_id"] = result.communication_id
    return state


def classify_appointment_customer_reply(state):
    result = AppointmentReplyClassificationService().classify_from_state(state)
    state.data.update(result.to_state_patch())
    return state


@safe_node
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
    if not result.ok and result.failure:
        raise WorkflowException(result.failure.code, result.failure.message)
    return state


@safe_node
def apply_turvo_delivery_appointment(state):
    result = AppointmentSchedulingTurvoWriteService().apply_delivery_from_state(state)
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
        raise WorkflowException(
            IntegrationError.VENDOR_API_ERROR,
            result.error or IntegrationError.VENDOR_API_ERROR.description,
        )
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


def apply_turvo_tender_status(state):
    if not state.data.get("confirmation_sent"):
        return state

    result = AppointmentSchedulingTurvoWriteService().tender_from_state(state)
    state.data["turvo_tender_result"] = {
        "ok": result.ok,
        "updated": result.updated,
        "skipped": result.skipped,
        "error": result.error,
        "response": result.response,
    }
    if result.ok and (result.updated or result.skipped):
        AppointmentSchedulingActivityService().record_turvo_tendered(state)
    if not result.ok:
        raise RuntimeError(result.error or "turvo_tender_failed")
    return state


def record_appointment_reply_completed(state):
    AppointmentSchedulingActivityService().record_reply_completed(state)
    return state


def record_appointment_reply_rejected(state):
    AppointmentSchedulingActivityService().record_reply_rejected(state)
    return state
