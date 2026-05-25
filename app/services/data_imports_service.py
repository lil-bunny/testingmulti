"""Orchestrate persistence of ingest results into ``data_imports``."""

from __future__ import annotations

from typing import Any, Optional

from app.models.data_import import DataImportDataType, DataImportSourceType
from app.repositories.data_imports_repository import DataImportsRepository


class DataImportsService:
    def __init__(self, repository: Optional[DataImportsRepository] = None) -> None:
        self._repository = repository or DataImportsRepository()

    def record_email_load_tendering_import(
        self,
        *,
        tenant_id: str,
        source_type: DataImportSourceType,
        file_name: str | None,
        mime_type: str | None,
        ingest_result: dict[str, Any],
    ) -> str:
        if not isinstance(ingest_result, dict):
            raise ValueError("ingest_result must be a dict")

        raw_dt = ingest_result.get("data_type")
        dtype = raw_dt.strip() if isinstance(raw_dt, str) else ""
        if not dtype:
            raise ValueError(
                "ingest_result must include non-blank data_type from ingest_data(...)"
            )

        validated_data_type = DataImportDataType(dtype).value

        raw_data = {
            "ingest": ingest_result,
            "mime_type": (mime_type or "").strip() or None,
        }
        return self._repository.insert(
            tenant_id=tenant_id,
            data_type=validated_data_type,
            source_type=source_type.value,
            file_name=file_name,
            raw_data=raw_data,
        )
