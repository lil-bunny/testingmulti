"""Tender ingest: duplicate order numbers in one import share one tender row."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.tenders_repository import TenderInsertResult
from app.services.tenders_ingest_service import TendersIngestService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DATA_IMPORT_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENDER_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _row(*, order_number: str, order_position: int, product_name: str = "Widget") -> dict:
    return {
        "order_number": order_number,
        "order_position": order_position,
        "customer_match": "Acme",
        "product_name": product_name,
        "order_quantity": 1,
    }


def test_duplicate_order_numbers_in_import_share_one_insert_and_tender_id() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
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
        tender_products_repository=products,
        delivery_locations=locations,
        pack_codes_repository=pack_codes,
    )
    ids = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[
            _row(order_number="93384", order_position=5, product_name="W1"),
            _row(order_number="93384", order_position=10, product_name="W2"),
            _row(order_number="95009", order_position=5, product_name="W3"),
        ],
    )

    assert ids == [TENDER_UUID, TENDER_UUID, "dddddddd-dddd-dddd-dddd-dddddddddddd"]
    batch = repo.insert_batch.call_args[0][0]
    assert len(batch) == 2
    assert batch[0]["order_number"] == "93384"
    assert batch[1]["order_number"] == "95009"
    assert len(products.insert_batch.call_args[0][0]) == 3


def test_existing_order_in_tenders_returns_none_for_workflow_enqueue() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
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
        tender_products_repository=products,
        delivery_locations=locations,
        pack_codes_repository=pack_codes,
    )
    ids = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[
            _row(order_number="93384", order_position=5),
            _row(order_number="95009", order_position=5),
        ],
    )

    assert ids == [None, "dddddddd-dddd-dddd-dddd-dddddddddddd"]
