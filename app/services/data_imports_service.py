"""Orchestrate persistence of ingest results into ``data_imports``."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from app.core.service_db import run_with_repos
from app.domain.gelita.email_attachments import (
    DELIVERY_LOCATIONS_FILE_NAME,
    is_delivery_locations_attachment,
)
from app.models.data_import import DataImportDataType, DataImportSourceType

if TYPE_CHECKING:
    from app.repositories.data_imports_repository import DataImportsRepository


class DataImportsService:
    def __init__(self, repository: Optional[DataImportsRepository] = None) -> None:
        self._repository = repository

    def _repo(self, repos: Any) -> DataImportsRepository:
        return self._repository or repos.data_imports

    def find_by_email_attachment_source(
        self,
        *,
        tenant_id: str,
        email_id: str,
        attachment_id: str,
    ) -> str | None:
        if self._repository is not None:
            return self._repository.find_id_by_email_attachment_source(
                tenant_id=tenant_id,
                email_id=email_id,
                attachment_id=attachment_id,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).find_id_by_email_attachment_source(
                tenant_id=tenant_id,
                email_id=email_id,
                attachment_id=attachment_id,
            )
        )

    def record_email_load_tendering_import(
        self,
        *,
        tenant_id: str,
        source_type: DataImportSourceType,
        file_name: str | None,
        mime_type: str | None,
        ingest_result: dict[str, Any],
        source: dict[str, str] | None = None,
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

        raw_data: dict[str, Any] = {
            "ingest": ingest_result,
            "mime_type": (mime_type or "").strip() or None,
        }
        if source:
            raw_data["source"] = {
                k: str(v).strip()
                for k, v in source.items()
                if v is not None and str(v).strip()
            }

        if self._repository is not None:
            return self._repository.insert(
                tenant_id=tenant_id,
                data_type=validated_data_type,
                source_type=source_type.value,
                file_name=file_name,
                raw_data=raw_data,
            )

        return run_with_repos(
            lambda repos: self._repo(repos).insert(
                tenant_id=tenant_id,
                data_type=validated_data_type,
                source_type=source_type.value,
                file_name=file_name,
                raw_data=raw_data,
            )
        )

    def _build_email_import_raw_data(
        self,
        *,
        ingest_result: dict[str, Any],
        mime_type: str | None,
        source: dict[str, str] | None,
    ) -> dict[str, Any]:
        raw_data: dict[str, Any] = {
            "ingest": ingest_result,
            "mime_type": (mime_type or "").strip() or None,
        }
        if source:
            raw_data["source"] = {
                k: str(v).strip()
                for k, v in source.items()
                if v is not None and str(v).strip()
            }
        return raw_data

    def record_email_delivery_locations_import(
        self,
        *,
        tenant_id: str,
        source_type: DataImportSourceType,
        file_name: str | None,
        mime_type: str | None,
        ingest_result: dict[str, Any],
        source: dict[str, str] | None = None,
    ) -> str:
        if not isinstance(ingest_result, dict):
            raise ValueError("ingest_result must be a dict")

        raw_dt = ingest_result.get("data_type")
        dtype = raw_dt.strip() if isinstance(raw_dt, str) else ""
        if dtype != DataImportDataType.DELIVERY_LOCATION.value:
            raise ValueError(
                "ingest_result data_type must be delivery_location for this method"
            )

        logical_name = (file_name or DELIVERY_LOCATIONS_FILE_NAME).strip()
        if not is_delivery_locations_attachment(logical_name):
            logical_name = DELIVERY_LOCATIONS_FILE_NAME

        raw_data = self._build_email_import_raw_data(
            ingest_result=ingest_result,
            mime_type=mime_type,
            source=source,
        )

        if self._repository is not None:
            existing_id = self._repository.find_id_by_tenant_data_type_and_file_name(
                tenant_id=tenant_id,
                data_type=DataImportDataType.DELIVERY_LOCATION.value,
                file_name=DELIVERY_LOCATIONS_FILE_NAME,
            )
            if existing_id:
                self._repository.update_raw_data(
                    tenant_id=tenant_id,
                    data_import_id=existing_id,
                    raw_data=raw_data,
                    file_name=DELIVERY_LOCATIONS_FILE_NAME,
                )
                return existing_id
            return self._repository.insert(
                tenant_id=tenant_id,
                data_type=DataImportDataType.DELIVERY_LOCATION.value,
                source_type=source_type.value,
                file_name=DELIVERY_LOCATIONS_FILE_NAME,
                raw_data=raw_data,
            )

        def _run(repos: Any) -> str:
            repo = self._repo(repos)
            existing_id = repo.find_id_by_tenant_data_type_and_file_name(
                tenant_id=tenant_id,
                data_type=DataImportDataType.DELIVERY_LOCATION.value,
                file_name=DELIVERY_LOCATIONS_FILE_NAME,
            )
            if existing_id:
                repo.update_raw_data(
                    tenant_id=tenant_id,
                    data_import_id=existing_id,
                    raw_data=raw_data,
                    file_name=DELIVERY_LOCATIONS_FILE_NAME,
                )
                return existing_id
            return repo.insert(
                tenant_id=tenant_id,
                data_type=DataImportDataType.DELIVERY_LOCATION.value,
                source_type=source_type.value,
                file_name=DELIVERY_LOCATIONS_FILE_NAME,
                raw_data=raw_data,
            )

        return run_with_repos(_run)
