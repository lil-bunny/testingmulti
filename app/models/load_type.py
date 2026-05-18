"""Domain enums for persisted load_type."""

from __future__ import annotations

from enum import StrEnum


class LoadType(StrEnum):
    """Row ``load_type`` for the ``tenders`` table."""

    LTL = "LTL" # Less-Than-Truckload
    FTL = "FTL" # Full Truckload
