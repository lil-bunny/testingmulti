"""Domain enums for persisted actor_type."""

from __future__ import annotations

from enum import StrEnum


class ActorType(StrEnum):
    """Row ``actor_type`` for the ``activity_logs`` table."""

    SYSTEM = "system"
    USER = "user"
