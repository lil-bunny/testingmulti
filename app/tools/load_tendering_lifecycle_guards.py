"""Execution-time guards for load_tendering reminder / escalation graph steps."""

from __future__ import annotations

from typing import Any

from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.status import StatusSubType, StatusType
from app.services.workflow_reminder_service import parse_reminders_for_workflow


def skip_sub_statuses_from_state(state: Any) -> frozenset[str]:
    """``tenant_settings.load_tendering.reminders.skip_sub_statuses`` for this run."""
    data = getattr(state, "data", None) or {}
    if not isinstance(data, dict):
        return frozenset()
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    if cfg is None:
        return frozenset()
    return frozenset(s.strip() for s in cfg.skip_sub_statuses if str(s).strip())


def delayed_workflow_step_skip_reason(
    row: dict[str, Any] | None,
    *,
    skip_sub_statuses: frozenset[str] | None = None,
) -> str | None:
    """
    Return a skip reason when reminder/escalation work must not run, else ``None``.

    Re-read lifecycle from DB immediately before send/apply (not only at graph entry).
    """
    if not row:
        return "lifecycle_not_found"

    if status_type_from_db(row.get("status")) == StatusType.COMPLETED:
        return "lifecycle_already_completed"

    sub = sub_status_type_from_db(row.get("sub_status"))
    if sub is not None:
        sub_s = sub.value
    else:
        sub_s = str(row.get("sub_status") or "").strip()

    terminal_subs = frozenset(
        {
            StatusSubType.ACCEPTED.value,
            StatusSubType.REJECTED.value,
            StatusSubType.DO_NOTHING.value,
        }
    )
    if sub_s in terminal_subs:
        return f"terminal_sub_status_{sub_s}"

    if skip_sub_statuses and sub_s in skip_sub_statuses:
        return f"skip_sub_status_{sub_s}"

    return None
