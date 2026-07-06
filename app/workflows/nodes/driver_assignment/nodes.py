"""Driver assignment workflow nodes (start + reminder_due paths)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.services.driver_assignment.escalation_service import DriverAssignmentEscalationService
from app.services.driver_assignment.activity_service import DriverAssignmentActivityService
from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from app.services.driver_assignment.turvo_service import DriverAssignmentTurvoService
from app.services.driver_assignment.classification_service import (
    DriverDetailsClassificationService,
)
from app.services.driver_assignment.shipment_driver_details_service import (
    DriverAssignmentShipmentDetailsService,
)
from app.services.workflow_reminder_service import WorkflowReminderService

logger = get_logger(__name__)


def check_driver_assignment_eligibility(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    exclude_run_id = str(state.execution_id or state.data.get("execution_id") or "").strip() or None
    result = DriverAssignmentIngressService().check_start_eligibility(
        tenant_id=tenant_id,
        tenant_settings=state.data.get("tenant_settings") or {},
        payload=state.data,
        exclude_run_id=exclude_run_id,
    )
    if result.skip_reason:
        state.data["driver_assignment_skip_reason"] = result.skip_reason
        state.data["driver_assignment_eligible"] = False
        logger.info(
            "check_driver_assignment_eligibility skip reason=%s lifecycle_id=%s",
            result.skip_reason,
            state.data.get("workflow_lifecycle_id"),
        )
    else:
        state.data["driver_assignment_eligible"] = True
    return state


def check_driver_reminder_eligibility(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    result = DriverAssignmentIngressService().check_reminder_eligibility(
        tenant_id=tenant_id,
        payload=state.data,
    )
    if result.skip_reason:
        state.data["driver_assignment_skip_reason"] = result.skip_reason
        state.data["driver_assignment_eligible"] = False
        logger.info(
            "check_driver_reminder_eligibility skip reason=%s lifecycle_id=%s",
            result.skip_reason,
            state.data.get("workflow_lifecycle_id"),
        )
    else:
        state.data["driver_assignment_eligible"] = True
    return state


def route_driver_assignment_delayed_event(state):
    return state


def check_driver_escalation_eligibility(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    result = DriverAssignmentIngressService().check_escalation_eligibility(
        tenant_id=tenant_id,
        payload=state.data,
    )
    if result.skip_reason:
        state.data["driver_assignment_skip_reason"] = result.skip_reason
        state.data["driver_assignment_eligible"] = False
        state.data["driver_escalation_skipped"] = result.skip_reason
        logger.info(
            "check_driver_escalation_eligibility skip reason=%s lifecycle_id=%s",
            result.skip_reason,
            state.data.get("workflow_lifecycle_id"),
        )
    else:
        state.data["driver_assignment_eligible"] = True
    return state


def escalate_driver_assignment(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip() or None
    result = DriverAssignmentEscalationService().escalate_from_payload(
        tenant_id=tenant_id,
        tenant_settings=state.data.get("tenant_settings") or {},
        payload=state.data,
        workflow_run_id=run_id,
    )
    state.data["driver_escalation_sent"] = result.sent
    if result.skip_reason:
        state.data["driver_escalation_skipped"] = result.skip_reason
    if result.error:
        state.data["driver_escalation_error"] = result.error
    return state


def send_driver_reminder(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip() or None
    result = DriverAssignmentIngressService().send_reminder_email(
        tenant_id=tenant_id,
        tenant_settings=state.data.get("tenant_settings") or {},
        payload=state.data,
        workflow_run_id=run_id,
    )
    state.data["driver_reminder_sent"] = result.sent
    if result.error:
        state.data["driver_reminder_error"] = result.error
    if result.communication_id:
        state.data["communication_id"] = result.communication_id
    return state


def record_driver_reminder_sent(state):
    DriverAssignmentActivityService().record_reminder_sent(state)
    return state


def record_driver_assignment_started(state):
    DriverAssignmentActivityService().record_started(state)
    return state


def schedule_driver_reminders(state):
    data = dict(state.data)
    WorkflowReminderService().schedule(data, workflow_name="driver_assignment")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True
    schedule = data.get("driver_reminder_schedule")
    if isinstance(schedule, dict):
        state.data["driver_reminder_schedule"] = schedule
        for key in (
            "pickup_appointment_at",
            "pickup_appointment_timezone",
            "pickup_appointment_source",
        ):
            if key in schedule and schedule[key] is not None:
                state.data[key] = schedule[key]
    return state


def classify_driver_details(state):
    result = DriverDetailsClassificationService().classify_from_state(state)
    state.data.update(result.to_state_patch())
    DriverAssignmentShipmentDetailsService().persist_extracted_from_state(state)
    return state


def route_tms_searchable(state):
    return state


def send_driver_details_partial_follow_up(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip() or None
    result = DriverAssignmentIngressService().send_partial_details_follow_up_email(
        tenant_id=tenant_id,
        tenant_settings=state.data.get("tenant_settings") or {},
        payload=state.data,
        workflow_run_id=run_id,
    )
    state.data["driver_reminder_sent"] = result.sent
    state.data["driver_reminder_is_partial_follow_up"] = result.sent
    if result.skip_sub_status_bump:
        state.data["driver_reminder_skip_sub_status_bump"] = True
    if result.reminder_step is not None:
        state.data["reminder_step"] = result.reminder_step
    if result.error:
        state.data["driver_reminder_error"] = result.error
    if result.communication_id:
        state.data["communication_id"] = result.communication_id
    return state


def resolve_turvo_driver(state):
    state.data.update(DriverAssignmentTurvoService().resolve_from_state(state))
    return state


def record_tms_driver_success(state):
    DriverAssignmentActivityService().record_tms_driver_success(state)
    DriverAssignmentShipmentDetailsService().persist_tms_matched_from_state(state)
    return state


def complete_driver_assignment_from_tms(state):
    DriverAssignmentActivityService().complete_when_driver_already_in_tms(state)
    return state


def record_tms_driver_not_resolved(state):
    DriverAssignmentActivityService().record_tms_driver_not_resolved(state)
    return state


def record_tms_driver_error(state):
    DriverAssignmentActivityService().record_tms_driver_error(state)
    return state


def send_driver_details_confirmation(state):
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip() or None
    result = DriverAssignmentIngressService().send_driver_details_confirmation_email(
        tenant_id=tenant_id,
        tenant_settings=state.data.get("tenant_settings") or {},
        payload=state.data,
        workflow_run_id=run_id,
    )
    state.data["driver_confirmation_sent"] = result.sent
    if result.error:
        state.data["driver_confirmation_error"] = result.error
    if result.communication_id:
        state.data["communication_id"] = result.communication_id
    return state


def record_driver_details_confirmation_sent(state):
    DriverAssignmentActivityService().record_driver_details_confirmation_sent(state)
    return state


def record_driver_assignment_completed(state):
    DriverAssignmentActivityService().record_driver_assignment_completed(state)
    return state
