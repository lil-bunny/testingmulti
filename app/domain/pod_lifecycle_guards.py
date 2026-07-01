"""Shared POD lifecycle sub-status guards."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.reminder_schedule import WorkflowRemindersConfig
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


def pod_reminder_skip_sub_statuses(data: dict[str, Any]) -> frozenset[str]:
    """``tenant_settings.pod_lifecycle.reminders.skip_sub_statuses`` from graph state."""
    block = (data.get("tenant_settings") or {}).get("pod_lifecycle")
    if not isinstance(block, dict):
        return frozenset()
    raw_reminders = block.get("reminders")
    if not isinstance(raw_reminders, dict):
        return frozenset()
    try:
        cfg = WorkflowRemindersConfig.model_validate(raw_reminders)
    except ValidationError:
        return frozenset()
    return frozenset(s.strip() for s in cfg.skip_sub_statuses if str(s).strip())
