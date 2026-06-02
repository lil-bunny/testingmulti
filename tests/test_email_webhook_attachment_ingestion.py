"""Tests for ``process_email_webhook_attachment_import`` return value (data_imports id)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.data_import import DataImportDataType
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.unipile_service import UnipileException


def _xlsx_payload() -> dict:
    return {
        "email_id": "mail-1",
        "account_id": "acc-1",
        "attachments": [
            {
                "id": "att-1",
                "name": "load.xlsx",
                "extension": "xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
    }


@pytest.mark.asyncio
async def test_process_returns_none_when_no_attachment() -> None:
    out = await process_email_webhook_attachment_import(
        payload={"attachments": [], "email_id": "e", "account_id": "a"},
        workflow_name="ratecon",
        data_import_tenant_id="aadc75f4-3f79-45d7-84c3-aa778e226e93",
    )
    assert out is None


@pytest.mark.asyncio
async def test_process_returns_none_when_fetch_context_incomplete() -> None:
    payload = {
        "attachments": [{"id": "1", "name": "a.xlsx", "extension": "xlsx"}],
    }
    out = await process_email_webhook_attachment_import(
        payload=payload,
        workflow_name="ratecon",
        data_import_tenant_id="aadc75f4-3f79-45d7-84c3-aa778e226e93",
    )
    assert out is None


@pytest.mark.asyncio
async def test_process_raises_on_unipile_fetch_failure() -> None:
    payload = _xlsx_payload()
    with patch(
        "app.services.email_webhook_attachment_ingestion.get_email_attachments",
        side_effect=UnipileException("fetch failed"),
    ):
        with pytest.raises(UnipileException, match="fetch failed"):
            await process_email_webhook_attachment_import(
                payload=payload,
                workflow_name="ratecon",
                data_import_tenant_id="aadc75f4-3f79-45d7-84c3-aa778e226e93",
            )


@pytest.mark.asyncio
async def test_process_returns_row_id_after_excel_ingest() -> None:
    payload = _xlsx_payload()
    ingest_result = {
        "status": "stubbed",
        "source_type": "email",
        "tenant_id": payload["account_id"],
        "data_type": "load_tender",
        "data": {},
        "file_name": "load.xlsx",
    }
    with (
        patch(
            "app.services.email_webhook_attachment_ingestion.get_email_attachments",
            return_value=b"fake-xlsx",
        ),
        patch(
            "app.services.email_webhook_attachment_ingestion.ingest_service.ingest_data",
            return_value=ingest_result,
        ),
        patch(
            "app.services.email_webhook_attachment_ingestion.DataImportsService",
        ) as svc_cls,
    ):
        svc_cls.return_value.find_by_email_attachment_source.return_value = None
        svc_cls.return_value.record_email_load_tendering_import.return_value = (
            "returned-import-uuid"
        )
        out = await process_email_webhook_attachment_import(
            payload=payload,
            workflow_name="ratecon",
            data_import_tenant_id="aadc75f4-3f79-45d7-84c3-aa778e226e93",
            data_import_data_type=DataImportDataType.LOAD_TENDER,
        )
    assert out == "returned-import-uuid"
    svc_cls.return_value.record_email_load_tendering_import.assert_called_once()
