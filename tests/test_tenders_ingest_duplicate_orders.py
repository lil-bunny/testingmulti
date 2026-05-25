"""Tender ingest: duplicate order numbers in one import share one tender row."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.repositories.tenders_repository import TenderInsertResult
from app.services.tenders_ingest_service import TendersIngestService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DATA_IMPORT_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENDER_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _mapped_row(*, order_number: str) -> dict:
    return {
        "order_number": order_number,
        "customer_name": "Acme",
        "product_name": "Widget",
        "order_quantity": Decimal("1"),
        "shipping_date": None,
        "delivery_date": None,
        "pickup_location_id": None,
        "delivery_location_id": None,
        "pack_code_id": None,
        "load_type": "LTL",
    }


@patch("app.services.tenders_ingest_service.projected_row_to_tender_insert")
def test_duplicate_order_numbers_in_import_share_one_insert_and_tender_id(
    mock_map: MagicMock,
) -> None:
    mock_map.side_effect = [
        _mapped_row(order_number="93384"),
        _mapped_row(order_number="93384"),
        _mapped_row(order_number="95009"),
    ]

    repo = MagicMock()
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=TENDER_UUID, created=True),
        TenderInsertResult(
            tender_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            created=True,
        ),
    ]

    locations = MagicMock()
    locations.index_for_ingest_run.return_value = {}

    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}

    svc = TendersIngestService(
        repository=repo,
        delivery_locations=locations,
        pack_codes_repository=pack_codes,
    )
    ids = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[{}, {}, {}],
    )

    assert ids == [TENDER_UUID, TENDER_UUID, "dddddddd-dddd-dddd-dddd-dddddddddddd"]
    batch = repo.insert_batch.call_args[0][0]
    assert len(batch) == 2
    assert batch[0]["order_number"] == "93384"
    assert batch[1]["order_number"] == "95009"


@patch("app.services.tenders_ingest_service.projected_row_to_tender_insert")
def test_existing_order_in_tenders_returns_none_for_workflow_enqueue(
    mock_map: MagicMock,
) -> None:
    mock_map.side_effect = [
        _mapped_row(order_number="93384"),
        _mapped_row(order_number="95009"),
    ]

    repo = MagicMock()
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=TENDER_UUID, created=False),
        TenderInsertResult(
            tender_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            created=True,
        ),
    ]

    locations = MagicMock()
    locations.index_for_ingest_run.return_value = {}
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}

    svc = TendersIngestService(
        repository=repo,
        delivery_locations=locations,
        pack_codes_repository=pack_codes,
    )
    ids = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[{}, {}],
    )

    assert ids == [None, "dddddddd-dddd-dddd-dddd-dddddddddddd"]
