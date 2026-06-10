"""Domain enums for persisted communication channels."""

from __future__ import annotations
from enum import StrEnum


class CommunicationChannel(StrEnum):
    """Row ``channel`` for the ``communications`` table."""

    SLACK = "slack"
    EMAIL = "email"
    TEAMS = "teams"
