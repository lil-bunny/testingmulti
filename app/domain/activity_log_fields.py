"""Map lifecycle state + ``activity_type`` to ``activity_logs`` status columns."""

from __future__ import annotations

from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.models.activity_type import ActivityType, is_snapshot_activity_type
from app.models.status import StatusSubType, StatusType


def status_for_log(value: StatusType | None) -> StatusType:
    """Use ``none`` when lifecycle status is unset or unparseable."""
    return value if value is not None else StatusType.NONE


def sub_status_for_log(value: StatusSubType | None) -> StatusSubType:
    return value if value is not None else StatusSubType.NONE


def build_activity_log_status_fields(
    command: LifecycleTransitionCommand,
    *,
    current_status: StatusType | None,
    current_sub: StatusSubType | None,
) -> tuple[StatusType, StatusType, StatusSubType, StatusSubType]:
    """
    Return ``(log_from_status, log_to_status, log_from_sub, log_to_sub)``.

    ``action`` / ``exception`` / ``info``: snapshot only — ``from_*`` and ``to_*`` equal current
    lifecycle state.
    ``status_change`` / ``sub_status_change``: transition — ``from_*`` from current,
    ``to_*`` from command when set else unchanged.
    """
    if is_snapshot_activity_type(command.activity_type):
        snap_status = status_for_log(current_status)
        snap_sub = sub_status_for_log(current_sub)
        return snap_status, snap_status, snap_sub, snap_sub

    log_from_status = status_for_log(current_status)
    log_from_sub = sub_status_for_log(current_sub)
    log_to_status = (
        command.to_status if command.to_status is not None else log_from_status
    )
    log_to_sub = (
        command.to_sub_status if command.to_sub_status is not None else log_from_sub
    )
    return log_from_status, log_to_status, log_from_sub, log_to_sub
