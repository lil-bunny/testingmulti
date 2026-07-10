"""Driver assignment lifecycle status guards (pure, no I/O)."""

from __future__ import annotations

from typing import Any

from app.configs.workflow_cancellation_policies import DRIVER_ASSIGNMENT_CANCEL_POLICY
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.domain.workflow_cancellation_guards import (
    is_workflow_cancelled,
    is_workflow_success_terminal,
)
from app.models.status import StatusSubType, StatusType

_REMINDER_LADDER_SUB_STATUSES = frozenset(
    {
        StatusSubType.REMINDER_1_SENT,
        StatusSubType.REMINDER_2_SENT,
        StatusSubType.REMINDER_3_SENT,
    }
)

DRIVER_ASSIGNMENT_REMINDER_SKIP_SUB_STATUSES = frozenset(
    {
        StatusSubType.UPLOADED_TO_TMS.value,
        StatusSubType.ESCALATED.value,
    }
)


def driver_assignment_reminder_skip_sub_statuses(
    _tenant_settings: dict[str, Any] | None = None,
) -> frozenset[str]:
    return DRIVER_ASSIGNMENT_REMINDER_SKIP_SUB_STATUSES


def is_driver_assignment_cancelled(
    status: StatusType | None,
    sub_status: StatusSubType | None,
) -> bool:
    return is_workflow_cancelled(status, sub_status)


def is_driver_assignment_active(
    status: StatusType | None,
    sub_status: StatusSubType | None,
) -> bool:
    return status == StatusType.PROCESSING and not is_driver_assignment_cancelled(
        status, sub_status
    )


def is_driver_assignment_success_terminal(
    status: StatusType | None,
    sub_status: StatusSubType | None,
) -> bool:
    return is_workflow_success_terminal(sub_status, DRIVER_ASSIGNMENT_CANCEL_POLICY)


def _status_sub_from_row(row: dict[str, Any] | None) -> tuple[StatusType | None, StatusSubType | None]:
    if not row:
        return None, None
    return (
        status_type_from_db(row.get("status")),
        sub_status_type_from_db(row.get("sub_status")),
    )


def blocks_driver_assignment_reminder(row: dict[str, Any] | None) -> bool:
    status, sub = _status_sub_from_row(row)
    if is_driver_assignment_cancelled(status, sub):
        return True
    if is_driver_assignment_success_terminal(status, sub):
        return True
    if status == StatusType.PENDING_REVIEW:
        return sub not in _REMINDER_LADDER_SUB_STATUSES
    if status is not None and status != StatusType.PROCESSING:
        return True
    return False


def blocks_driver_assignment_escalation(row: dict[str, Any] | None) -> bool:
    """True when escalation must not run (cancelled, success terminal, or already escalated)."""
    status, sub = _status_sub_from_row(row)
    if is_driver_assignment_cancelled(status, sub):
        return True
    if is_driver_assignment_success_terminal(status, sub):
        return True
    if sub == StatusSubType.ESCALATED:
        return True
    if status == StatusType.COMPLETED:
        return True
    return False
