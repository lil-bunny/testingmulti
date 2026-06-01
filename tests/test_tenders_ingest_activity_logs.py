"""Tender ingest no longer writes activity_logs (logged on workflow run instead)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.repositories.tenders_repository import TenderInsertResult
from app.services.tenders_ingest_service import TendersIngestService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENDER_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DATA_IMPORT_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _projected_row() -> dict:
    return {
        "order_number": "ORD-1",
        "order_position": 5,
        "customer_match": "Acme Corp",
        "product_name": "Widget",
        "order_quantity": Decimal("100"),
    }


def test_ingest_does_not_write_activity_logs() -> None:
    mock_repo = MagicMock()
    mock_repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=TENDER_UUID, created=True),
    ]
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}

    svc = TendersIngestService(
        repository=mock_repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )
    out = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[_projected_row()],
    )

    assert out == [TENDER_UUID]
