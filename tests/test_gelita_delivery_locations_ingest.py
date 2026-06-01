"""Gelita delivery_location.xlsx email ingest — parent entrypoints and routing only."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.delivery_locations_data_import import (
    load_delivery_location_rows_from_data_import,
)
from app.services.delivery_locations_email_ingest_service import (
    process_delivery_locations_from_email_webhook,
)
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.unipile_tenant_resolution import UnipileTenantContext

_TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_DATA_IMPORT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _gelita_tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=_TENANT_UUID,
        tenant_slug="gelita",
    )


def _spreadsheet_raw(*, sheet_name: str, rows: list[dict] | None) -> dict:
    return {
        "ingest": {
            "data": {
                "spreadsheet": {
                    "format": "xlsx",
                    "sheets": [{"name": sheet_name, "rows": rows}],
                }
            }
        }
    }


@patch("app.services.gelita_inbound_email_service.enqueue_load_tendering_tender_created_ingest")
@patch("app.services.gelita_inbound_email_service.enqueue_delivery_locations_import")
def test_gelita_dl_only_email_queues_delivery_locations_not_tender(
    mock_dl_enqueue: MagicMock,
    mock_tender_enqueue: MagicMock,
) -> None:
    mock_dl_enqueue.return_value = ("task-dl", "queued")
    payload = {
        "webhook_name": "gelita",
        "has_attachments": True,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
        ],
    }
    svc = GelitaInboundEmailService()
    svc._communications = MagicMock()
    asyncio.run(svc.handle(payload=payload, tenant=_gelita_tenant()))

    mock_dl_enqueue.assert_called_once()
    mock_tender_enqueue.assert_not_called()


@patch("app.services.gelita_inbound_email_service.enqueue_load_tendering_tender_created_ingest")
@patch("app.services.gelita_inbound_email_service.enqueue_delivery_locations_import")
def test_gelita_email_with_dl_and_tender_enqueues_both(
    mock_dl_enqueue: MagicMock,
    mock_tender_enqueue: MagicMock,
) -> None:
    mock_dl_enqueue.return_value = ("task-dl", "queued")
    mock_tender_enqueue.return_value = ("task-tender", "queued")
    payload = {
        "webhook_name": "gelita",
        "has_attachments": True,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "2", "extension": "xlsx", "name": "Customer_Orders.xlsx"},
        ],
    }
    svc = GelitaInboundEmailService()
    svc._communications = MagicMock()
    asyncio.run(svc.handle(payload=payload, tenant=_gelita_tenant()))

    mock_dl_enqueue.assert_called_once()
    mock_tender_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_process_delivery_locations_from_email_webhook_persists_import() -> None:
    with patch(
        "app.services.delivery_locations_email_ingest_service."
        "process_delivery_locations_attachment_import",
        new_callable=AsyncMock,
        return_value=_DATA_IMPORT_ID,
    ):
        result = await process_delivery_locations_from_email_webhook(
            payload={"email_id": "e1"},
            tenant_uuid=_TENANT_UUID,
        )

    assert result == {
        "message": "success",
        "event_type": "delivery_locations_updated",
        "data_import_id": _DATA_IMPORT_ID,
    }


@pytest.mark.parametrize(
    ("sheet_name", "rows"),
    [
        (
            "Delivery locations",
            [{"delviery": "41000100", "City": "SIOUX CITY"}],
        ),
        (
            "Sheet1",
            [{"delviery": "41000100", "City": "SIOUX CITY"}],
        ),
        ("Sheet1", []),
    ],
    ids=["named_tab", "fallback_tab", "empty_workbook"],
)
def test_load_delivery_location_rows_from_stored_import(
    sheet_name: str,
    rows: list[dict],
) -> None:
    repo = MagicMock()
    repo.find_id_by_tenant_data_type_and_file_name.return_value = _DATA_IMPORT_ID
    repo.fetch_raw_data_by_id.return_value = _spreadsheet_raw(
        sheet_name=sheet_name,
        rows=rows,
    )

    with patch(
        "app.services.delivery_locations_data_import.DataImportsRepository",
        return_value=repo,
    ):
        loaded = load_delivery_location_rows_from_data_import(_TENANT_UUID)

    if not rows:
        assert loaded == []
    else:
        assert len(loaded) == 1
        assert loaded[0]["City"] == "SIOUX CITY"
