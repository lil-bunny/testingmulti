"""Tender ingest no longer writes activity_logs (logged on workflow run instead)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.tenders_ingest_service import TendersIngestService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENDER_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DATA_IMPORT_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _projected_row() -> dict:
    return {
        "order_number": "ORD-1",
        "customer_match": "Acme Corp",
        "product_name": "Widget",
        "order_quantity": Decimal("100"),
    }


@patch("app.services.tenders_ingest_service.projected_row_to_tender_insert")
def test_ingest_does_not_write_activity_logs(mock_map: MagicMock) -> None:
    mock_map.return_value = {
        "order_number": "ORD-1",
        "customer_name": "Acme Corp",
        "product_name": "Widget",
        "order_quantity": Decimal("100"),
        "shipping_date": None,
        "delivery_date": None,
        "pickup_location_id": None,
        "delivery_location_id": None,
        "pack_code_id": None,
        "load_type": "ltl",
    }
    mock_repo = MagicMock()
    mock_repo.insert_batch.return_value = [TENDER_UUID]

    svc = TendersIngestService(repository=mock_repo)
    out = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[_projected_row()],
    )

    assert out == [TENDER_UUID]
