"""Gelita-only delivery_location.xlsx flow: email routing, ingest, column layout, tender lookup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.configs.gelita_delivery_locations_columns import (
    GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS,
)
from app.repositories.tenders_repository import TenderInsertResult
from app.services.delivery_locations_data_import import (
    load_delivery_location_rows_from_data_import,
)
from app.services.delivery_locations_email_ingest_service import (
    process_delivery_locations_from_email_webhook,
)
from app.services.delivery_locations_service import DeliveryLocationsService
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.tenders_ingest_service import TendersIngestService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from tests.helpers.delivery_location_rows import row_with_cells

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


def _positional_delivery_row() -> dict:
    """Headerless wide row: delivery code in column C, city in Q (Gelita layout)."""
    return row_with_cells(C="41000100", Q="SIOUX CITY")


def _ingest_svc_with_products(repo: MagicMock) -> TendersIngestService:
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    return TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )


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
            {"id": "2", "extension": "xlsx", "name": "customers_orders_ship_schedule.xlsx"},
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


def test_gelita_wide_column_mapping_materializes_address_fields() -> None:
    row = row_with_cells(
        C="41000100",
        E="CARRIER CLAIMS",
        J="MERICAL",
        L="1420 STEUBEN STREET",
        N="51105",
        Q="SIOUX CITY",
        BJ="U.S.A.",
    )
    out = GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS.materialize_from_column_letters(row)
    assert out["delviery"] == "41000100"
    assert out["Customer Name"] == "MERICAL"
    assert out["City"] == "SIOUX CITY"
    assert out["Zip Code"] == "51105"


def test_delivery_locations_index_for_ingest_run_none_on_provider_failure() -> None:
    def failing_provider() -> list[dict]:
        raise RuntimeError("data_import unavailable")

    svc = DeliveryLocationsService(rows_provider=failing_provider)
    assert svc.index_for_ingest_run() is None


@pytest.mark.parametrize(
    ("sheet_name", "rows"),
    [
        ("Delivery locations", [_positional_delivery_row()]),
        ("Sheet1", [_positional_delivery_row()]),
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
        "app.services.delivery_locations_data_import.run_with_repos",
        side_effect=lambda fn: fn(MagicMock(data_imports=repo)),
    ):
        loaded = load_delivery_location_rows_from_data_import(_TENANT_UUID)

    if not rows:
        assert loaded == []
        return

    assert len(loaded) == 1
    svc = DeliveryLocationsService(
        rows_provider=lambda: loaded,
        column_mapping=GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS,
    )
    hit = svc.lookup("41000100")
    assert hit is not None
    assert hit["City"] == "SIOUX CITY"


def test_ingest_attaches_delivery_address_from_wide_column_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.tenders_ingest_service.lookup_state",
        lambda _country, _postal: "IA",
    )

    wide_row = row_with_cells(
        C="41000100",
        E="CARRIER CLAIMS ABF FREIGHT",
        J="MERICAL",
        L="1420 STEUBEN STREET",
        N="51105",
        Q="SIOUX CITY",
        BJ="U.S.A.",
    )
    locations = DeliveryLocationsService(
        rows_provider=lambda: [wide_row],
        column_mapping=GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS,
    )

    repo = MagicMock()
    tender_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]

    svc = _ingest_svc_with_products(repo)
    svc._delivery_locations = locations
    rows = [
        {
            "order_number": "N-wide",
            "order_position": 1,
            "weight_unit": "KG",
            "customer_match": "KDMATCH_IGNORED",
            "product_name": "P",
            "order_quantity": 2,
            "delivery_address_code": "41000100",
        },
    ]
    ids = svc.persist_from_projected_rows(
        tenant_id=_TENANT_UUID,
        data_import_id=_DATA_IMPORT_ID,
        projected_rows=rows,
    )
    assert ids == [tender_uuid]
    batch = repo.insert_batch.call_args[0][0]
    assert batch[0]["customer_name"] == "MERICAL"
    assert batch[0]["metadata"]["customer_name_source"] == "delivery_location"
    assert batch[0]["delivery_address"]["city"] == "SIOUX CITY"
    assert batch[0]["delivery_address"]["name"] == "CARRIER CLAIMS ABF FREIGHT"
