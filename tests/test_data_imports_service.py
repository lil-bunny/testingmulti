"""Tests for ``DataImportsService`` orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.data_import import DataImportSourceType
from app.services.data_imports_service import DataImportsService


def test_record_email_load_tendering_builds_raw_data_and_calls_repo() -> None:
    repo = MagicMock()
    repo.insert.return_value = "new-uuid-here"

    svc = DataImportsService(repository=repo)
    ingest = {
        "status": "stubbed",
        "source_type": "email",
        "data_type": "load_tender",
        "data": {},
    }
    oid = svc.record_email_load_tendering_import(
        tenant_id="  tenant-uuid  ",
        source_type=DataImportSourceType.EMAIL,
        file_name="Orders.xlsx",
        mime_type=" application/vnd.sheet ",
        ingest_result=ingest,
    )

    assert oid == "new-uuid-here"
    repo.insert.assert_called_once()
    kw = repo.insert.call_args.kwargs
    assert kw["tenant_id"] == "  tenant-uuid  "
    assert kw["data_type"] == "load_tender"
    assert kw["source_type"] == "email"
    assert kw["file_name"] == "Orders.xlsx"
    assert kw["raw_data"] == {
        "ingest": ingest,
        "mime_type": "application/vnd.sheet",
    }


def test_record_email_load_tendering_requires_data_type_from_ingest_result() -> None:
    svc = DataImportsService(repository=MagicMock())
    with pytest.raises(ValueError, match="data_type"):
        svc.record_email_load_tendering_import(
            tenant_id="t",
            source_type=DataImportSourceType.EMAIL,
            file_name=None,
            mime_type=None,
            ingest_result={"status": "stubbed"},
        )


def test_record_email_load_tendering_rejects_non_dict_ingest() -> None:
    svc = DataImportsService(repository=MagicMock())
    with pytest.raises(ValueError, match="ingest_result must be a dict"):
        svc.record_email_load_tendering_import(
            tenant_id="t",
            source_type=DataImportSourceType.EMAIL,
            file_name=None,
            mime_type=None,
            ingest_result=[],  # type: ignore[arg-type]
        )
