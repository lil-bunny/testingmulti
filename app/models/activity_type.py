"""Enums for ``activity_logs`` row classification."""

from __future__ import annotations

from enum import StrEnum


class ActivityType(StrEnum):
    """``activity_logs.activity_type`` — how the row should be interpreted."""

    ACTION = "action"
    EXCEPTION = "exception"
    STATUS_CHANGE = "status_change"
    SUB_STATUS_CHANGE = "sub_status_change"


def is_snapshot_activity_type(activity_type: ActivityType) -> bool:
    return activity_type in (ActivityType.ACTION, ActivityType.EXCEPTION)


class ActorType(StrEnum):
    """``activity_logs.actor_type``."""

    SYSTEM = "system"
    USER = "user"


# Sentinel UUID for ``actor_type=system`` when no user initiated the action (no FK).
SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"
