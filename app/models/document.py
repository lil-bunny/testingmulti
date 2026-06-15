"""Domain enums for persisted freight documents."""

from __future__ import annotations

from enum import StrEnum


class DocumentType(StrEnum):
    """Row ``type`` for the ``documents`` table (Postgres enum / CHECK)."""

    POD = "pod"
    RATECON = "ratecon"
