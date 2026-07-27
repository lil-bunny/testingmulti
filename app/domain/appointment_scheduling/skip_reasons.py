"""Map appointment-scheduling skip wire strings to error catalog entries."""

from __future__ import annotations

from app.domain.error_catalog import (
    BusinessError,
    ErrorCode,
    IntegrationError,
    SystemError,
    format_error_message,
)

# Wire strings shared with ingress / intake.
SKIP_MISSING_RECIPIENT_EMAIL = "missing_recipient_email"
SKIP_MISSING_APPOINTMENT_DATA_SOURCE = "missing_appointment_data_source"
SKIP_APPOINTMENT_SHEET_UNREADABLE = "appointment_sheet_unreadable"
SKIP_APPOINTMENT_MODE_NOT_EMAIL = "appointment_mode_not_email"

# In-graph integration wire codes (services set error=...; nodes map via from_wire).
WIRE_TURVO_SHIPMENT_FETCH_FAILED = "turvo_shipment_fetch_failed"
WIRE_TURVO_STOP_UPDATE_FAILED = "turvo_stop_update_failed"
WIRE_TURVO_TENDER_STATUS_FAILED = "turvo_tender_status_failed"

_SKIP_TO_CATALOG: dict[str, ErrorCode] = {
    # Business — tenant / sheet / contact
    SKIP_MISSING_RECIPIENT_EMAIL: BusinessError.MISSING_RECIPIENT_EMAIL,
    SKIP_MISSING_APPOINTMENT_DATA_SOURCE: BusinessError.MISSING_APPOINTMENT_DATA_SOURCE,
    SKIP_APPOINTMENT_SHEET_UNREADABLE: BusinessError.APPOINTMENT_SHEET_UNREADABLE,
    SKIP_APPOINTMENT_MODE_NOT_EMAIL: BusinessError.APPOINTMENT_MODE_NOT_EMAIL,
    "ascend_not_configured": BusinessError.ASCEND_NOT_CONFIGURED,
    "pickup_dropoff_extract_failed": BusinessError.ASCEND_PICKUP_DROPOFF_EXTRACT_FAILED,
    "invalid_ascend_payload": BusinessError.ASCEND_INVALID_PAYLOAD,
    "invalid_ascend_pickup_plan": BusinessError.ASCEND_INVALID_PAYLOAD,
    "missing_reference_or_appointment_time": BusinessError.ASCEND_MISSING_REFERENCE,
    "missing_shipment_id": BusinessError.SCHEDULING_MISSING_SHIPMENT_ID,
    "missing_mikey_account_id": BusinessError.MISSING_MIKEY_ACCOUNT_ID,
    "missing_email_draft": BusinessError.SCHEDULING_DRAFT_NOT_READY,
    "missing_thread_or_tenant": BusinessError.SCHEDULING_DRAFT_NOT_READY,
    "missing_turvo_update_fields": BusinessError.MISSING_TURVO_UPDATE_FIELDS,
    "missing_turvo_shipment_fields": BusinessError.MISSING_TURVO_UPDATE_FIELDS,
    "missing_delivery_stop_or_date": BusinessError.MISSING_DELIVERY_STOP_OR_DATE,
    "missing_turvo_tender_fields": BusinessError.MISSING_TURVO_TENDER_FIELDS,
    "missing_fragment_id": BusinessError.MISSING_TURVO_FRAGMENT_ID,
    # Integration — Ascend / Turvo
    WIRE_TURVO_SHIPMENT_FETCH_FAILED: IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
    WIRE_TURVO_STOP_UPDATE_FAILED: IntegrationError.TURVO_STOP_UPDATE_FAILED,
    WIRE_TURVO_TENDER_STATUS_FAILED: IntegrationError.TURVO_TENDER_STATUS_FAILED,
    # Pre-graph lifecycle / ingress operational (mark_restartable_skip; not in-graph raises)
    "enqueue_failed": SystemError.UNEXPECTED_NODE_FAILURE,
    "lifecycle_create_failed": SystemError.UNEXPECTED_NODE_FAILURE,
    "tenant_not_resolved": SystemError.UNEXPECTED_NODE_FAILURE,
    # Ingress logging only (reference used for Ascend/office resolution)
    "missing_reference_number": BusinessError.ASCEND_MISSING_REFERENCE,
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
