"""Tests for ``projected_row_to_tender_insert`` and ``TendersIngestService``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.domain.load_tendering_tender_rows import (
    projected_row_to_tender_insert,
    resolve_pack_code_id,
)
from app.repositories.tenders_repository import TenderInsertResult
from app.services.tenders_ingest_service import TendersIngestService


def test_mapper_happy_path() -> None:
    row = {
        "order_number": "PO-1",
        "customer_match": "Acme",
        "product_name": "Widget",
        "order_quantity": 12,
        "delivery_date": "2026-06-01",
        "shipping_date": "2026-05-15T00:00:00",
        "pack_code_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
    }
    out = projected_row_to_tender_insert(row)
    assert out is not None
    assert out["order_number"] == "PO-1"
    assert out["customer_name"] == "Acme"
    assert out["product_name"] == "Widget"
    assert out["order_quantity"] == Decimal("12")
    assert out["delivery_date"] == date(2026, 6, 1)
    assert out["shipping_date"] == date(2026, 5, 15)
    assert out["pack_code_id"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
    assert out["load_type"] == "LTL"
    assert out["metadata"] == {}


def test_mapper_metadata_po_number_from_besttxt() -> None:
    row = {
        "order_number": "PO-1",
        "customer_match": "Acme",
        "product_name": "Widget",
        "order_quantity": 1,
        "po_number": "4500123456",
    }
    out = projected_row_to_tender_insert(row)
    assert out is not None
    assert out["metadata"] == {"po_number": "4500123456"}


def test_mapper_metadata_empty_when_po_number_blank() -> None:
    row = {
        "order_number": "PO-1",
        "customer_match": "Acme",
        "product_name": "Widget",
        "order_quantity": 1,
        "po_number": "   ",
    }
    out = projected_row_to_tender_insert(row)
    assert out is not None
    assert out["metadata"] == {}


def test_mapper_skips_blank_order_number() -> None:
    assert projected_row_to_tender_insert({"order_number": "  "}) is None


def test_mapper_skips_blank_customer_or_product() -> None:
    assert (
        projected_row_to_tender_insert(
            {
                "order_number": "1",
                "customer_match": "",
                "product_name": "P",
                "order_quantity": 1,
            }
        )
        is None
    )
    assert (
        projected_row_to_tender_insert(
            {
                "order_number": "1",
                "customer_match": "B",
                "product_name": "  ",
                "order_quantity": 1,
            }
        )
        is None
    )


def test_mapper_skips_invalid_quantity() -> None:
    assert (
        projected_row_to_tender_insert(
            {
                "order_number": "1",
                "customer_match": "B",
                "product_name": "P",
                "order_quantity": "nope",
            }
        )
        is None
    )


def test_mapper_unknown_pack_code_text_becomes_null_id() -> None:
    row = {
        "order_number": "1",
        "customer_match": "B",
        "product_name": "P",
        "order_quantity": 1,
        "pack_code": "9999",
    }
    out = projected_row_to_tender_insert(row, active_pack_code_index={})
    assert out is not None
    assert out["pack_code_id"] is None


def test_mapper_resolves_pack_code_text_via_index() -> None:
    row = {
        "order_number": "1",
        "customer_match": "B",
        "product_name": "P",
        "order_quantity": 1,
        "pack_code": " 5137 ",
    }
    index = {"5137": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"}
    out = projected_row_to_tender_insert(row, active_pack_code_index=index)
    assert out is not None
    assert out["pack_code_id"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


def test_resolve_pack_code_id_exact_match_trims_spaces_only() -> None:
    index = {"5137": "uuid-5137"}
    assert resolve_pack_code_id({"pack_code": " 5137 "}, active_pack_code_index=index) == "uuid-5137"
    assert resolve_pack_code_id({"pack_code": "05137"}, active_pack_code_index=index) is None


def _ingest_svc(repo: MagicMock) -> TendersIngestService:
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    return TendersIngestService(repository=repo, pack_codes_repository=pack_codes)


def test_ingest_service_noop_without_import_id() -> None:
    repo = MagicMock()
    svc = _ingest_svc(repo)
    assert (
        svc.persist_from_projected_rows(
            tenant_id="t",
            data_import_id=None,
            projected_rows=[{"order_number": "1"}],
        )
        == []
    )
    repo.insert_batch.assert_not_called()


def test_ingest_service_batches_valid_rows() -> None:
    repo = MagicMock()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]
    svc = _ingest_svc(repo)
    rows = [
        {
            "order_number": "N1",
            "customer_match": "C",
            "product_name": "P",
            "order_quantity": 2,
        },
        {"order_number": ""},
    ]
    ids_by_row = svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    assert ids_by_row == [tender_uuid, None]
    repo.insert_batch.assert_called_once()
    batch = repo.insert_batch.call_args[0][0]
    assert len(batch) == 1
    assert batch[0]["tenant_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert batch[0]["data_import_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert batch[0]["order_number"] == "N1"
    assert batch[0]["metadata"] == {}


def test_ingest_service_passes_metadata_po_number_to_repository() -> None:
    repo = MagicMock()
    repo.insert_batch.return_value = [
        TenderInsertResult(
            tender_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            created=True,
        ),
    ]
    svc = _ingest_svc(repo)
    rows = [
        {
            "order_number": "N1",
            "customer_match": "C",
            "product_name": "P",
            "order_quantity": 2,
            "po_number": "BEST-PO-1",
        },
    ]
    svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    batch = repo.insert_batch.call_args[0][0]
    assert batch[0]["metadata"] == {"po_number": "BEST-PO-1"}
