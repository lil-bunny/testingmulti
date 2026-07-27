from app.core.logger import get_logger
from app.domain.ingest_source_fields import pack_code_for_product_gap
from app.domain.gelita.routing_guide_lifecycle import routing_guide_attempt_from_state
from app.domain.load_tendering_settings import (
    is_ftl_load_type,
    resolve_load_type,
    routing_guide_max_attempts,
)
from app.domain.pod_lifecycle.guards import pod_email_status_eligible_from_turvo_payload
from app.domain.load_tendering_state import get_tender, get_tender_products
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
        if state.data.get("event_type") == "reminder_due":
            return "exists_on_reminder"
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
        status_ok = pod_email_status_eligible_from_turvo_payload(shipment)
        if event_type == "manual_pod_upload":
            if not status_ok:
                return "invalid_shipment_status"
            if state.data.get("manual_pod_upload_source") == "stored":
                return "manual_pod_stored"
            return "manual_pod_process"
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
    if state.data.get("event_type") == "manual_pod_upload":
        return "manual_skip"
    return "missing"


def post_pod_processing_router(state):
    """After LLM pipeline: manual portal uploads to TMS; email updates shipment."""
    if state.data.get("event_type") == "manual_pod_upload":
        return "manual"
    return "email"


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


def driver_assignment_delayed_eligibility_router(state):
    if state.data.get("driver_assignment_eligible"):
        return "eligible"
    if state.data.get("driver_assignment_skip_reason") == "driver_already_assigned":
        return "driver_already_assigned"
    return "skip"


def pod_reminder_eligibility_router(state):
    if state.data.get("pod_reminder_eligible"):
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
    if state.data.get("stale_routing_guide_reminder"):
        return "completed"
    if state.data.get("workflow_lifecycle_status") == StatusType.COMPLETED.value:
        return "completed"
    event_type = state.data.get("event_type")
    if event_type in ("reminder_due", "escalation_due"):
        if is_past_delivery_cutoff(state.data):
            return "completed"
        return event_type
    return "missing"


def manual_tms_upload_router(state):
    """Manual portal path: continue processing after TMS upload unless re-uploading stored POD."""
    outcome = str(state.data.get("pod_tms_upload_outcome") or "").strip()
    if outcome not in ("uploaded", "skipped"):
        return "stop"
    if state.data.get("manual_pod_upload_source") == "stored":
        return "stop"
    return "continue"


def automatic_reply_ack_router(state):
    """Route ack_received past automatic-reply guard before carrier ack LLM."""
    if state.data.get("retired_carrier_thread_ack") or state.data.get(
        "automatic_reply_skipped"
    ):
        return "skipped"
    return "continue"


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


def routing_guide_router(state):
    """Route reject/timeout to advance, exhausted, or LTL terminal."""
    # Shipper-domain reject (inbound_routing_emails[0] domain): terminal, no advance.
    if state.data.get("routing_guide_shipper_domain_reject"):
        return "ltl_terminal"
    if not is_ftl_load_type(resolve_load_type(state)):
        return "ltl_terminal"
    attempt = routing_guide_attempt_from_state(state.data)
    if attempt < routing_guide_max_attempts(state):
        return "advance"
    return "exhausted"


def domestic_delivery_router(state):
    return "domestic" if state.data.get("is_domestic_delivery") else "international"


def driver_details_router(state):
    """Route driver_details_email_received LLM decision to graph branch keys."""
    decision = str(state.data.get("driver_details_decision") or DO_NOTHING).strip()
    if decision in (HAS_DETAILS, INSUFFICIENT, DO_NOTHING):
        return decision
    return DO_NOTHING


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


def post_read_tender_router(state):
    """Route after ``read_tender_row`` by event type, failover, pack-code skip, or tender status."""
    if state.data.get("routing_guide_failover"):
        return "routing_guide_failover"
    event_type = str(state.data.get("event_type") or "").strip()
    if event_type == "carrier_email_received":
        return "carrier_email_received"
    if event_type == "tender_created":
        if not state.data.get("is_domestic_delivery"):
            return "international"
        skipped = frozenset(state.data.get("skipped_pack_codes") or ())
        if skipped:
            tender = get_tender(state.data) or {}
            for product in get_tender_products(tender):
                if pack_code_for_product_gap(product) in skipped:
                    return "pack_code_skipped"
        return "domestic"
    return tender_status_router(state)