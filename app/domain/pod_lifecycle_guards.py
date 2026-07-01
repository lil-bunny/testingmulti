"""Shared POD lifecycle sub-status guards."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.models.status import StatusSubType

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
