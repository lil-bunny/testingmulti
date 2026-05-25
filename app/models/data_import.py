"""Domain enums for persisted ``data_imports`` classification."""

from __future__ import annotations

from enum import StrEnum


class DataImportSourceType(StrEnum):
    """``data_imports.source_type`` — channel the payload arrived on."""

    EMAIL = "email"
    API = "api"


class DataImportDataType(StrEnum):
    """``data_imports.data_type`` — business kind of imported payload."""

    LOAD_TENDER = "load_tender"
