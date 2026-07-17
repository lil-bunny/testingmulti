"""Shared POD lifecycle sub-status guards."""

from __future__ import annotations

from typing import Any

from app.domain.status_parsing import sub_status_type_from_db
from app.models.status import StatusSubType
from app.models.workflow_run_event_type import WorkflowRunEventType

POD_UPLOAD_ACTIVITY_DONE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_UPLOADED,
        StatusSubType.DOCUMENT_PROCESSED,
    }
)

POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_PROCESSED,
    }
)

POD_PROCESSING_COMPLETE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_PROCESSED,
        StatusSubType.UPLOADED_TO_TMS,
        StatusSubType.RESOLVED_MANUALLY,
    }
)

# Route complete, EnRoute, At Delivery — same set as shipment_router email_received gate.
POD_EMAIL_ALLOWED_TURVO_STATUS_KEYS = frozenset({"2116", "2106", "2105"})


def is_convoy_from_turvo_shipment_payload(shipment: dict[str, Any]) -> bool:
    """True when carrier is Convoy — mirrors ``get_shipment`` node convoy detection."""
    if not isinstance(shipment, dict):
        return False
    details = shipment.get("details") or {}
    carrier_order = details.get("carrierOrder") or []
    carrier_name = ""
    if carrier_order and isinstance(carrier_order[0], dict):
        carrier = carrier_order[0].get("carrier") or {}
        carrier_name = str(carrier.get("name") or "")
    if carrier_name:
        return "convoy" in carrier_name.lower()
    return bool(shipment.get("convoy", False))


def pod_email_status_eligible_from_turvo_payload(shipment: dict[str, Any]) -> bool:
    """True when Turvo shipment status allows POD email ingress / processing."""
    status_key = (
        (shipment.get("details") or {})
        .get("status", {})
        .get("code", {})
        .get("key")
    )
    return str(status_key) in POD_EMAIL_ALLOWED_TURVO_STATUS_KEYS


def is_pod_processing_complete_sub_status(sub: StatusSubType | None) -> bool:
    """True when POD extraction pipeline finished (duplicate email gate)."""
    return sub in POD_PROCESSING_COMPLETE_SUB_STATUSES


def is_manual_pod_upload(data: dict[str, Any]) -> bool:
    return str(data.get("event_type") or "").strip() == WorkflowRunEventType.MANUAL_POD_UPLOAD.value


def is_email_pod_event(data: dict[str, Any]) -> bool:
    return str(data.get("event_type") or "").strip() == WorkflowRunEventType.EMAIL_RECEIVED.value


def pod_upload_success_from_state(data: dict[str, Any]) -> bool:
    """True when POD document is stored or manual upload keys are present."""
    pod_persist = data.get("documents_pod")
    if isinstance(pod_persist, dict) and pod_persist.get("stored") is True:
        return True

    normalization = data.get("attachment_normalization")
    if isinstance(normalization, dict):
        merged_key = data.get("pod_merged_pdf_object_key")
        if normalization.get("success") and merged_key and str(merged_key).strip():
            return True

    event_type = str(data.get("event_type") or "").strip()
    pod_keys = data.get("pod_object_keys") or []
    if event_type == WorkflowRunEventType.MANUAL_POD_UPLOAD.value and pod_keys:
        return True

    return False


def is_manual_fresh_pod_upload(data: dict[str, Any]) -> bool:
    """Portal upload with a new PDF (not stored-only TMS re-push)."""
    if not is_manual_pod_upload(data):
        return False
    return data.get("manual_pod_upload_source") != "stored"


def should_skip_idempotent_pod_activity_log(
    data: dict[str, Any],
    lifecycle_row: dict[str, Any] | None,
    *,
    done_sub_statuses: frozenset[StatusSubType],
) -> bool:
    """Skip duplicate activity rows for email retries; manual fresh uploads always log."""
    if is_manual_fresh_pod_upload(data):
        return False
    sub = sub_status_type_from_db(lifecycle_row.get("sub_status")) if lifecycle_row else None
    return sub is not None and sub in done_sub_statuses


def pod_reminder_skip_sub_statuses(_data: dict[str, Any] | None = None) -> frozenset[str]:
    """Hardcoded reminder skip list — same milestones as duplicate-email POD complete gate."""
    return frozenset(s.value for s in POD_PROCESSING_COMPLETE_SUB_STATUSES)


def pod_attachment_gate_eligible(normalization: dict[str, Any]) -> bool:
    """True when attachment assess/normalize succeeded."""
    return bool(normalization.get("success"))


ATTACHMENT_CLASSIFIER_FAILED = "attachment_classifier_failed"


def pod_attachment_gate_skip_reason(normalization: dict[str, Any]) -> str | None:
    """Skip reason from assess/normalize failure; None when eligible."""
    if pod_attachment_gate_eligible(normalization):
        return None
    err = str(normalization.get("error") or "")
    if err == ATTACHMENT_CLASSIFIER_FAILED:
        return ATTACHMENT_CLASSIFIER_FAILED
    if (
        "rejected_by_classifier" in err
        or "No valid document" in err
        or err.startswith("prefilter:")
    ):
        return "invalid_attachment"
    if err in ("download_failed",) or "unsupported_type" in err:
        return "unsupported_attachment"
    if err == "No attachments provided":
        return "no_attachments"
    return "attachment_normalization_failed"
