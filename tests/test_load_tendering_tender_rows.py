"""Tests for tender row mappers, dedupe, and ``TendersIngestService``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domain.delivery_address import (
    CUSTOMER_NAME_PLACEHOLDER,
    CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
    CUSTOMER_NAME_SOURCE_UNKNOWN,
    resolve_customer_name,
)
from app.domain.delivery_locations import DeliveryLocationsIndex
from app.domain.load_tendering_tender_rows import (
    dedupe_projected_rows_by_order_and_position,
    parse_order_position,
    parse_weight_unit,
    projected_row_to_tender_insert,
    projected_row_to_tender_product_insert,
    resolve_pack_code_id,
)
from app.repositories.tenders_repository import TenderInsertResult
from app.services.tenders_ingest_service import TendersIngestService


def test_parse_order_position_accepts_excel_float() -> None:
    assert parse_order_position(10.0) == 10
    assert parse_order_position("10") == 10
    assert parse_order_position(0) is None
    assert parse_order_position(None) is None


def test_dedupe_keeps_distinct_positions_drops_duplicate() -> None:
    rows = [
        {"order_number": "123", "order_position": 10},
        {"order_number": "123", "order_position": 10},
        {"order_number": "123", "order_position": 5},
    ]
    kept = dedupe_projected_rows_by_order_and_position(rows)
    assert [i for i, _ in kept] == [0, 2]


def test_mapper_header_happy_path() -> None:
    row = {
        "order_number": "PO-1",
        "customer_match": "ShipScheduleName",
        "weight_unit": "KG",
        "delivery_date": "2026-06-01",
        "shipping_date": "2026-05-15T00:00:00",
    }
    out = projected_row_to_tender_insert(
        row,
        customer_name="Acme",
        customer_name_source=CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
    )
    assert out is not None
    assert out["order_number"] == "PO-1"
    assert out["customer_name"] == "Acme"
    assert "product_name" not in out
    assert out["delivery_date"] == date(2026, 6, 1)
    assert out["shipping_date"] == date(2026, 5, 15)
    assert out["load_type"] == "LTL"
    assert "weight_unit" not in out
    assert out["metadata"] == {"customer_name_source": CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION}


def test_mapper_product_happy_path() -> None:
    row = {
        "order_number": "PO-1",
        "order_position": 5,
        "product_name": "Widget",
        "order_quantity": 12,
        "price_per_unit": "123.45",
        "weight_unit": "KG",
        "pack_code_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
    }
    out = projected_row_to_tender_product_insert(row)
    assert out is not None
    assert out["product_name"] == "Widget"
    assert out["order_quantity"] == Decimal("12")
    assert out["price_per_unit"] == Decimal("123.45")
    assert out["weight_unit"] == "kg"
    assert out["pack_code_id"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


def test_mapper_metadata_po_number_from_besttxt() -> None:
    row = {
        "order_number": "PO-1",
        "weight_unit": "LB",
        "po_number": "4500123456",
    }
    out = projected_row_to_tender_insert(
        row,
        customer_name="Acme",
        customer_name_source=CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
    )
    assert out is not None
    assert out["metadata"] == {
        "po_number": "4500123456",
        "customer_name_source": CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
    }


def test_mapper_metadata_empty_when_po_number_blank() -> None:
    row = {
        "order_number": "PO-1",
        "weight_unit": "kg",
        "po_number": "   ",
    }
    out = projected_row_to_tender_insert(
        row,
        customer_name="Acme",
        customer_name_source=CUSTOMER_NAME_SOURCE_UNKNOWN,
    )
    assert out is not None
    assert out["metadata"] == {"customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN}


def test_mapper_skips_blank_order_number() -> None:
    assert projected_row_to_tender_insert({"order_number": "  "}) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KG", "kg"),
        ("KGM", "kg"),
        ("lb", "lb"),
        ("LBS", "lb"),
        ("  LB  ", "lb"),
        (None, None),
        ("", None),
        ("TON", None),
    ],
)
def test_parse_weight_unit_normalizes_me(raw: str | None, expected: str | None) -> None:
    assert parse_weight_unit(raw) == expected


def test_mapper_skips_invalid_weight_unit() -> None:
    assert (
        projected_row_to_tender_product_insert(
            {
                "order_number": "1",
                "order_position": 5,
                "product_name": "P",
                "order_quantity": 1,
                "weight_unit": "TON",
            }
        )
        is None
    )


def test_mapper_skips_blank_customer_name_param() -> None:
    assert (
        projected_row_to_tender_insert(
            {"order_number": "1", "customer_match": "Ignored"},
            customer_name="  ",
        )
        is None
    )


@pytest.mark.parametrize(
    ("location_rows", "delivery_code", "expected_name", "expected_source"),
    [
        (
            [{"delviery": "41000100", "Customer Name": "MERICAL"}],
            "41000100",
            "MERICAL",
            CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
        ),
        (
            [{"delviery": "41000100", "Customer Name": "MERICAL", "Name": "Addr Name"}],
            "41000100",
            "MERICAL",
            CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
        ),
        (
            [{"delviery": "41000100", "Customer Name": None, "Name": "Addr Name"}],
            "41000100",
            CUSTOMER_NAME_PLACEHOLDER,
            CUSTOMER_NAME_SOURCE_UNKNOWN,
        ),
        (None, "41000100", CUSTOMER_NAME_PLACEHOLDER, CUSTOMER_NAME_SOURCE_UNKNOWN),
        (
            [{"delviery": "41000100", "Customer Name": "MERICAL"}],
            "999",
            CUSTOMER_NAME_PLACEHOLDER,
            CUSTOMER_NAME_SOURCE_UNKNOWN,
        ),
    ],
)
def test_resolve_customer_name_column_j_only(
    location_rows: list[dict] | None,
    delivery_code: str,
    expected_name: str,
    expected_source: str,
) -> None:
    index = (
        DeliveryLocationsIndex(location_rows) if location_rows is not None else None
    )
    name, source = resolve_customer_name(delivery_code, index)
    assert name == expected_name
    assert source == expected_source


def test_product_mapper_skips_blank_product_or_invalid_qty() -> None:
    assert (
        projected_row_to_tender_product_insert(
            {
                "order_number": "1",
                "order_position": 5,
                "customer_match": "B",
                "product_name": "  ",
                "order_quantity": 1,
                "weight_unit": "KG",
            }
        )
        is None
    )
    assert (
        projected_row_to_tender_product_insert(
            {
                "order_number": "1",
                "order_position": 5,
                "product_name": "P",
                "order_quantity": "nope",
                "weight_unit": "KG",
            }
        )
        is None
    )


def test_product_mapper_unknown_pack_code_text_becomes_null_id() -> None:
    row = {
        "order_number": "1",
        "order_position": 1,
        "product_name": "P",
        "order_quantity": 1,
        "weight_unit": "KG",
        "pack_code": "9999",
    }
    out = projected_row_to_tender_product_insert(row, active_pack_code_index={})
    assert out is not None
    assert out["pack_code_id"] is None


def test_product_mapper_resolves_pack_code_text_via_index() -> None:
    row = {
        "order_number": "1",
        "order_position": 1,
        "product_name": "P",
        "order_quantity": 1,
        "weight_unit": "KG",
        "pack_code": " 5137 ",
    }
    index = {"5137": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"}
    out = projected_row_to_tender_product_insert(row, active_pack_code_index=index)
    assert out is not None
    assert out["pack_code_id"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


def test_resolve_pack_code_id_exact_match_trims_spaces_only() -> None:
    index = {"5137": "uuid-5137"}
    assert resolve_pack_code_id({"pack_code": " 5137 "}, active_pack_code_index=index) == "uuid-5137"
    assert resolve_pack_code_id({"pack_code": "05137"}, active_pack_code_index=index) is None


def _ingest_svc(repo: MagicMock) -> TendersIngestService:
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    return TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )


def test_ingest_service_noop_without_import_id() -> None:
    repo = MagicMock()
    svc = _ingest_svc(repo)
    assert (
        svc.persist_from_projected_rows(
            tenant_id="t",
            data_import_id=None,
            projected_rows=[{"order_number": "1", "order_position": 1}],
        )
        == []
    )
    repo.insert_batch.assert_not_called()


def test_ingest_service_batches_valid_rows() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    svc = TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )
    rows = [
        {
            "order_number": "N1",
            "order_position": 1,
            "weight_unit": "KG",
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
    assert batch[0]["customer_name"] == CUSTOMER_NAME_PLACEHOLDER
    assert batch[0]["metadata"] == {"customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN}
    products.insert_batch.assert_called_once()
    product_batch = products.insert_batch.call_args[0][0]
    assert len(product_batch) == 1
    assert product_batch[0]["tender_id"] == tender_uuid
    assert product_batch[0]["weight_unit"] == "kg"


def test_ingest_service_passes_metadata_po_number_to_repository() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    repo.insert_batch.return_value = [
        TenderInsertResult(
            tender_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            created=True,
        ),
    ]
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    svc = TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )
    rows = [
        {
            "order_number": "N1",
            "order_position": 1,
            "weight_unit": "LB",
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
    assert batch[0]["metadata"] == {
        "po_number": "BEST-PO-1",
        "customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN,
    }
    product_batch = products.insert_batch.call_args[0][0]
    assert product_batch[0]["weight_unit"] == "lb"


def test_ingest_duplicate_order_position_inserts_one_product_line() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    svc = TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )
    rows = [
        {
            "order_number": "123",
            "order_position": 10,
            "weight_unit": "KG",
            "product_name": "A",
            "order_quantity": 1,
        },
        {
            "order_number": "123",
            "order_position": 10,
            "weight_unit": "KG",
            "product_name": "B",
            "order_quantity": 2,
        },
        {
            "order_number": "123",
            "order_position": 5,
            "weight_unit": "KG",
            "product_name": "C",
            "order_quantity": 3,
        },
    ]
    ids = svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    assert ids == [tender_uuid, None, tender_uuid]
    product_batch = products.insert_batch.call_args[0][0]
    assert len(product_batch) == 2
    names = {p["product_name"] for p in product_batch}
    assert names == {"A", "C"}


def test_ingest_same_order_distinct_weight_unit_per_product_line() -> None:
    repo = MagicMock()
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    svc = TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )
    rows = [
        {
            "order_number": "93384",
            "order_position": 5,
            "weight_unit": "KG",
            "product_name": "Widget A",
            "order_quantity": 1,
        },
        {
            "order_number": "93384",
            "order_position": 10,
            "weight_unit": "LB",
            "product_name": "Widget B",
            "order_quantity": 2,
        },
    ]
    svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    assert len(repo.insert_batch.call_args[0][0]) == 1
    product_batch = products.insert_batch.call_args[0][0]
    assert len(product_batch) == 2
    units_by_name = {p["product_name"]: p["weight_unit"] for p in product_batch}
    assert units_by_name == {"Widget A": "kg", "Widget B": "lb"}
