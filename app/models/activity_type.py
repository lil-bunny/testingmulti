"""Enums for ``activity_logs`` row classification."""

from __future__ import annotations

from enum import StrEnum


class ActivityType(StrEnum):
    """``activity_logs.activity_type`` — how the row should be interpreted."""

    ACTION = "action"
    STATUS_CHANGE = "status_change"
    SUB_STATUS_CHANGE = "sub_status_change"


class ActorType(StrEnum):
    """``activity_logs.actor_type``."""

    SYSTEM = "system"
    USER = "user"


# Sentinel UUID for ``actor_type=system`` when no user initiated the action (no FK).
SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"
