"""Tests for spreadsheet extraction, column projection, and data import read orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.configs.load_tendering_import_projection import LOAD_TENDERING_ROW_PROJECTION
from app.domain.column_projection import (
    drop_all_empty_projected_rows,
    projected_row_has_any_value,
    project_row,
)
from app.domain.data_import_tabular import iter_spreadsheet_rows
from app.services.data_imports_read_service import DataImportsReadService


def _sample_raw_data() -> dict:
    return {
        "ingest": {
            "data": {
                "spreadsheet": {
                    "format": "xlsx",
                    "sheets": [
                        {
                            "name": "SheetA",
                            "row_count": 1,
                            "rows": [
                                {
                                    "Customer Match": "Acme",
                                    "Order quantity": 10,
                                },
                            ],
                        },
                        {
                            "name": "SheetB",
                            "row_count": 1,
                            "rows": [
                                {
                                    "CUSTOMER MATCH": "Other",
                                    "order #": "PO-1",
                                },
                            ],
                        },
                    ],
                }
            },
        },
        "mime_type": "application/vnd.sheet",
    }


def test_iter_spreadsheet_rows_yields_all_sheets_with_sheet_name() -> None:
    rows = list(iter_spreadsheet_rows(_sample_raw_data()))
    assert len(rows) == 2
    assert rows[0]["_sheet_name"] == "SheetA"
    assert rows[0]["Customer Match"] == "Acme"
    assert rows[1]["_sheet_name"] == "SheetB"
    assert rows[1]["CUSTOMER MATCH"] == "Other"


def test_iter_spreadsheet_rows_empty_when_wrong_format() -> None:
    raw = {
        "ingest": {
            "data": {"spreadsheet": {"format": "csv", "sheets": [{"name": "x", "rows": [{}]}]}}
        }
    }
    assert list(iter_spreadsheet_rows(raw)) == []


def test_drop_all_empty_projected_rows() -> None:
    rows = [
        {"customer_match": "X", "order_quantity": None},
        {"customer_match": None, "order_quantity": None},
        {"customer_match": "  ", "order_quantity": None},
    ]
    out = drop_all_empty_projected_rows(rows)
    assert len(out) == 1
    assert out[0]["customer_match"] == "X"


def test_projected_row_has_any_value_numeric_zero_counts() -> None:
    row = {"order_quantity": 0, "customer_match": None}
    assert projected_row_has_any_value(row)


def test_project_row_case_insensitive_and_aliases() -> None:
    row = {
        "  customer match  ": "X",
        "Order #": "N-99",
        "Pack code": "P1",
    }
    out = project_row(row, LOAD_TENDERING_ROW_PROJECTION)
    assert out["customer_match"] == "X"
    assert out["order_number"] == "N-99"
    assert out["pack_code"] == "P1"
    assert out["product_name"] is None
    assert out["shipping_date"] is None
    assert out["delivery_date"] is None
    assert out["order_quantity"] is None


def test_project_row_maps_order_position() -> None:
    row = {"Order position": 10, "Order #": "123"}
    out = project_row(row, LOAD_TENDERING_ROW_PROJECTION)
    assert out["order_position"] == 10
    assert out["order_number"] == "123"


def test_project_row_maps_besttxt_to_po_number() -> None:
    row = {"BESTTXT": "PO-4500123", "Customer Match": "Acme"}
    out = project_row(row, LOAD_TENDERING_ROW_PROJECTION)
    assert out["po_number"] == "PO-4500123"
    assert out["customer_match"] == "Acme"


def test_project_row_besttxt_case_insensitive() -> None:
    row = {" besttxt ": "  PO-99  "}
    out = project_row(row, LOAD_TENDERING_ROW_PROJECTION)
    assert out["po_number"] == "  PO-99  "


def test_project_row_maps_gelita_sap_column_aliases() -> None:
    row = {
        "ANR": "ORD-100",
        "KDMATCH": "Acme GmbH",
        "LIEFAN": "DL-42",
        "TEXT1": "Widget A",
        "ARTSPEZ": "PK-1",
        "EINTREFFDAT": "2026-06-01",
        "LIEDAT": "2026-05-28",
        "MEBEST": 12,
        "ME": "KG",
        "POSIT": 10,
    }
    out = project_row(row, LOAD_TENDERING_ROW_PROJECTION)
    assert out["order_number"] == "ORD-100"
    assert out["order_position"] == 10
    assert out["customer_match"] == "Acme GmbH"
    assert out["delivery_address_code"] == "DL-42"
    assert out["product_name"] == "Widget A"
    assert out["pack_code"] == "PK-1"
    assert out["delivery_date"] == "2026-06-01"
    assert out["shipping_date"] == "2026-05-28"
    assert out["order_quantity"] == 12
    assert out["weight_unit"] == "KG"


def test_data_imports_read_service_none_when_missing_row() -> None:
    repo = MagicMock()
    repo.fetch_raw_data_by_id.return_value = None
    svc = DataImportsReadService(repository=repo)
    rows, meta = svc.get_projected_rows(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projection=LOAD_TENDERING_ROW_PROJECTION,
    )
    assert rows is None
    assert meta == {}


def test_data_imports_read_service_empty_when_no_spreadsheet() -> None:
    repo = MagicMock()
    repo.fetch_raw_data_by_id.return_value = {"ingest": {"data": {}}}
    svc = DataImportsReadService(repository=repo)
    rows, meta = svc.get_projected_rows(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projection=LOAD_TENDERING_ROW_PROJECTION,
    )
    assert rows == []
    assert meta.get("reason") == "no_spreadsheet"


def test_data_imports_read_service_projects_rows() -> None:
    repo = MagicMock()
    repo.fetch_raw_data_by_id.return_value = _sample_raw_data()
    svc = DataImportsReadService(repository=repo)
    rows, meta = svc.get_projected_rows(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projection=LOAD_TENDERING_ROW_PROJECTION,
    )
    assert meta.get("source") == "spreadsheet"
    assert rows is not None and len(rows) == 2
    assert rows[0]["customer_match"] == "Acme"
    assert rows[0]["order_quantity"] == 10
    assert rows[1]["customer_match"] == "Other"
    assert rows[1]["order_number"] == "PO-1"


def test_data_imports_read_service_filters_all_none_projected_rows() -> None:
    raw = {
        "ingest": {
            "data": {
                "spreadsheet": {
                    "format": "xlsx",
                    "sheets": [
                        {
                            "name": "S",
                            "row_count": 2,
                            "rows": [
                                {
                                    "Customer Match": "A",
                                    "Product name": "P",
                                    "Order quantity": 1,
                                    "Order #": "1",
                                },
                                {},
                            ],
                        }
                    ],
                }
            },
        },
        "mime_type": "application/vnd.sheet",
    }
    repo = MagicMock()
    repo.fetch_raw_data_by_id.return_value = raw
    svc = DataImportsReadService(repository=repo)
    rows, meta = svc.get_projected_rows(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projection=LOAD_TENDERING_ROW_PROJECTION,
    )
    assert meta.get("source") == "spreadsheet"
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["customer_match"] == "A"

