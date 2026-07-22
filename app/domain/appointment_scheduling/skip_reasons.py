"""Map legacy appointment-scheduling skip strings to error catalog entries."""

from __future__ import annotations

from app.domain.error_catalog import (
    BusinessError,
    ErrorCode,
    IntegrationError,
    SystemError,
    format_error_message,
)

# Wire strings shared with ingress / intake (promoted from recipient_contact_gate).
SKIP_MISSING_RECIPIENT_EMAIL = "missing_recipient_email"
SKIP_MISSING_APPOINTMENT_DATA_SOURCE = "missing_appointment_data_source"
SKIP_APPOINTMENT_SHEET_UNREADABLE = "appointment_sheet_unreadable"
SKIP_APPOINTMENT_MODE_NOT_EMAIL = "appointment_mode_not_email"

_SKIP_TO_CATALOG: dict[str, ErrorCode] = {
    # Business — tenant / sheet / contact
    SKIP_MISSING_RECIPIENT_EMAIL: BusinessError.MISSING_RECIPIENT_EMAIL,
    SKIP_MISSING_APPOINTMENT_DATA_SOURCE: BusinessError.MISSING_APPOINTMENT_DATA_SOURCE,
    SKIP_APPOINTMENT_SHEET_UNREADABLE: BusinessError.APPOINTMENT_SHEET_UNREADABLE,
    SKIP_APPOINTMENT_MODE_NOT_EMAIL: BusinessError.APPOINTMENT_MODE_NOT_EMAIL,
    "ascend_not_configured": BusinessError.ASCEND_NOT_CONFIGURED,
    "missing_ascend_credentials": BusinessError.ASCEND_NOT_CONFIGURED,
    "pickup_dropoff_extract_failed": BusinessError.ASCEND_PICKUP_DROPOFF_EXTRACT_FAILED,
    "invalid_ascend_payload": BusinessError.ASCEND_INVALID_PAYLOAD,
    "invalid_ascend_pickup_plan": BusinessError.ASCEND_INVALID_PAYLOAD,
    "missing_reference_or_appointment_time": BusinessError.ASCEND_MISSING_REFERENCE,
    "missing_shipment_id": BusinessError.SCHEDULING_MISSING_SHIPMENT_ID,
    "intake_failed": SystemError.UNEXPECTED_NODE_FAILURE,
    # Integration — Ascend (legacy coarse codes)
    "ascend_fetch_failed": IntegrationError.ASCEND_SHIPMENT_FETCH_FAILED,
    # Ingress-only (log mapping; no activity row)
    "process_disabled": BusinessError.ASCEND_NOT_CONFIGURED,
    "turvo_not_configured": SystemError.UNEXPECTED_NODE_FAILURE,
    "event_not_shipment_update": SystemError.UNEXPECTED_NODE_FAILURE,
    "status_not_tender_accepted": SystemError.UNEXPECTED_NODE_FAILURE,
    "no_pickup_change": SystemError.UNEXPECTED_NODE_FAILURE,
    "multi_stop": SystemError.UNEXPECTED_NODE_FAILURE,
    "missing_reference_number": BusinessError.ASCEND_MISSING_REFERENCE,
    "non_diamond_customer": SystemError.UNEXPECTED_NODE_FAILURE,
    "missing_load_id": SystemError.UNEXPECTED_NODE_FAILURE,
    "duplicate_lifecycle": SystemError.UNEXPECTED_NODE_FAILURE,
    "turvo_shipment_fetch_failed": IntegrationError.TMS_CONNECTION_TIMED_OUT,
    "turvo_activity_fetch_failed": IntegrationError.TMS_CONNECTION_TIMED_OUT,
    "tenant_not_resolved": SystemError.UNEXPECTED_NODE_FAILURE,
    "lifecycle_create_failed": SystemError.UNEXPECTED_NODE_FAILURE,
    "enqueue_failed": SystemError.UNEXPECTED_NODE_FAILURE,
}


def resolve_scheduling_error(
    skip_reason: str,
    **context: str,
) -> tuple[ErrorCode, str] | None:
    """Return catalog member and formatted message for a skip wire string."""
    key = str(skip_reason or "").strip()
    if not key:
        return None
    catalog = _SKIP_TO_CATALOG.get(key)
    if catalog is None:
        return None
    message = format_error_message(catalog, **context)
    return catalog, message


def scheduling_failure_from_skip(
    skip_reason: str,
    **context: str,
) -> "SchedulingFailure | None":
    from app.domain.appointment_scheduling.failure import SchedulingFailure

    resolved = resolve_scheduling_error(skip_reason, **context)
    if resolved is None:
        return None
    catalog, message = resolved
    return SchedulingFailure.from_catalog(catalog, message)
