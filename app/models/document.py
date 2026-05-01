"""Domain enums for persisted freight documents."""

from __future__ import annotations

from enum import StrEnum


class DocumentType(StrEnum):
    """Row ``type`` for the ``documents`` table (Postgres enum / CHECK)."""

    POD_ATTACHMENT = "pod_attachment"
    POD_MERGED_FINAL = "pod_merged_final"
    RATECON = "ratecon"
