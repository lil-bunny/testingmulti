from app.core.logger import get_logger
from app.domain.load_tendering_state import get_tender
from app.models.status import StatusSubType, StatusType
from app.tools.driver_details import (
    DO_NOTHING,
    HAS_DETAILS,
    INSUFFICIENT,
    has_partial_driver_fields,
    has_tms_searchable_fields,
)
from app.tools.tender_reminder_delivery_cutoff import is_past_delivery_cutoff

logger = get_logger(__name__)


def pod_exists_router(state):
    return "exists" if state.data.get("pod_exists") else "missing"


def pod_missing_dispatch_router(state):
    """
    POD missing:
    - route_completed: schedule Celery steps 0–2 only (no synchronous email).
    - reminder_due: send email in this run (after Turvo check), i.e. queued reminder fired.
    - anything else: no send; only scheduled reminders may mail.
    """
    if state.data.get("pod_exists"):
        return "exists"
    if state.data.get("event_type") == "route_completed":
        return "schedule_initial"
    if state.data.get("event_type") == "reminder_due":
        return "send_now"
    return "skip_send"


def shipment_router(state):
    event_type = event_type_router(state)

    if event_type in ("email_received", "manual_pod_upload"):
        shipment = state.data.get("shipment") or {}
        status_key = (
            shipment.get("details", {})
            .get("status", {})
            .get("code", {})
            .get("key")
        )
        allowed_status_codes = {"2116", "2106", "2105"} # Route Complete, EnRoute, At Delivery
        status_ok = str(status_key) in allowed_status_codes
        if event_type == "manual_pod_upload":
            return "manual_pod_valid" if status_ok else "invalid_shipment_status"
        return "valid_shipment_status" if status_ok else "invalid_shipment_status"

    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def ratecon_cache_router(state):
    """Route POD processing only when cached ratecon extraction is available."""
    rc = state.data.get("ratecon_analysis_results") or {}
    if rc.get("success") and not rc.get("skipped"):
        findings = rc.get("findings") or {}
        extracted = findings.get("extracted_fields") or {}
        if extracted:
            return "ready"
    return "missing"


def read_workflow_lifecycle_router(state):
    event_type = event_type_router(state)
    if event_type in ("email_received", "manual_pod_upload"):
        lifecycle = (
            state.data.get("lookup_workflow_lifecycle")
            or state.data.get("workflow_lifecycle_payload")
            or state.data.get("ratecon_workflow_lifecycle")
            or {}
        )
        return "is_found" if lifecycle.get("found") else "missing"
    return "missing"


def event_type_router(state):
    event_type = state.data.get("event_type")
    # Gelita load_tendering (router map keys must match workflow_configs targets)
    if event_type in (
        "tender_created",
        "carrier_email_received",
        "ack_received",
        "reminder_due",
        "escalation_due",
    ):
        return event_type
    if event_type == "email_received":
        return "email_received"
    if event_type == "manual_pod_upload":
        return "manual_pod_upload"
    if event_type == "ratecon_completed":
        return "ratecon_completed"
    if event_type == "driver_details_email_received":
        return "driver_details_email_received"
    return "route_completed"


def driver_assignment_eligibility_router(state):
    if state.data.get("driver_assignment_eligible"):
        return "eligible"
    return "skip"


def driver_assignment_delayed_event_router(state):
    if state.data.get("event_type") == "escalation_due":
        return "escalation_due"
    return "reminder_due"


def load_type_router(state):
    """
    Route by computed order load type from ``calculate_tender_params``.

    Uses ``state.data['tender']['load_type']`` (``LTL`` / ``FTL``).
    """
    tender = get_tender(state.data) or {}
    load_type = str(tender.get("load_type") or "").strip().upper()
    return "ftl_path" if load_type == "FTL" else "ltl_path"


def tender_status_router(state):
    if state.data.get("workflow_lifecycle_status") == StatusType.COMPLETED.value:
        return "completed"
    event_type = state.data.get("event_type")
    if event_type in ("reminder_due", "escalation_due"):
        if is_past_delivery_cutoff(state.data):
            tender = get_tender(state.data) or {}
            logger.info(
                "tender_status_router skipping past delivery cutoff "
                "event_type=%s tender_id=%s delivery_date=%s lifecycle_id=%s",
                event_type,
                state.data.get("tender_id"),
                tender.get("delivery_date"),
                state.data.get("workflow_lifecycle_id"),
            )
            return "completed"
        return event_type
    return "missing"


def manual_tms_upload_router(state):
    """Manual portal path: continue processing after TMS upload succeeded or was skipped."""
    outcome = str(state.data.get("pod_tms_upload_outcome") or "").strip()
    if outcome in ("uploaded", "skipped"):
        return "continue"
    return "stop"


def carrier_ack_router(state):
    """Route ack_received LLM decision to graph branch keys."""
    decision = str(
        state.data.get("carrier_ack_decision") or StatusSubType.DO_NOTHING.value
    ).strip()
    if decision in (
        StatusSubType.ACCEPTED.value,
        StatusSubType.REJECTED.value,
        StatusSubType.DO_NOTHING.value,
    ):
        return decision
    return StatusSubType.DO_NOTHING.value


def driver_details_router(state):
    """Route driver_details_email_received LLM decision to graph branch keys."""
    decision = str(state.data.get("driver_details_decision") or DO_NOTHING).strip()
    if decision in (HAS_DETAILS, INSUFFICIENT, DO_NOTHING):
        return decision
    return DO_NOTHING


def driver_details_partial_router(state):
    """Route insufficient replies: partial fields → follow-up, else end."""
    extraction = state.data.get("driver_details_extraction") or {}
    driver = extraction.get("driver") if isinstance(extraction, dict) else {}
    if isinstance(driver, dict) and has_partial_driver_fields(driver):
        return "partial_fields"
    return "no_partial_fields"


def tms_searchable_router(state):
    """Insufficient branch: TMS search when name/phone present, else follow-up or end."""
    extraction = state.data.get("driver_details_extraction") or {}
    driver = extraction.get("driver") if isinstance(extraction, dict) else {}
    if isinstance(driver, dict) and has_tms_searchable_fields(driver):
        return "searchable"
    if isinstance(driver, dict) and has_partial_driver_fields(driver):
        return "follow_up_only"
    return "none"


def tms_driver_router(state):
    """Route TMS driver resolution outcome."""
    outcome = str(state.data.get("tms_driver_outcome") or "").strip()
    if outcome == "assigned":
        return "assigned"
    if outcome == "follow_up":
        return "follow_up"
    if outcome == "error":
        return "error"
    return "error"
def domestic_delivery_router(state):
    return "domestic" if state.data.get("is_domestic_delivery") else "international"


def post_read_tender_router(state):
    event_type = str(state.data.get("event_type") or "").strip()
    if event_type == "tender_created":
        return domestic_delivery_router(state)
    return tender_status_router(state)
