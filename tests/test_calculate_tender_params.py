"""
Tests for Gelita ``calculate_tender_params`` using DB-backed fixtures (orders 96564 / 96399).

Product and pack_code fields were captured from ``tenders`` / ``tender_products`` /
``pack_codes`` for tenant ``aadc75f4-3f79-45d7-84c3-aa778e226e92``.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.load_tendering_state import get_tender
from app.domain.state import WorkflowState
from app.tools.tender_email import (
    TenderEmailProductLine,
    _format_price,
    _ftl_products_block,
    _ltl_products_block,
    build_tender_email_input_from_tender,
)
from app.workflows.nodes.gelita.calculate_tender_params import (
    calculate_tender_params,
    gelita_calculate_params,
)

_TENANT_SETTINGS_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "tenant_settings"
    / "gelita.tenant_settings.dev.json"
)

# Live DB snapshot (order_number → tender / products / pack_codes)
TENANT_ID = "aadc75f4-3f79-45d7-84c3-aa778e226e92"
PACK_CODE_ID = "9d579b89-2280-4fb0-8f1b-12acf9c5f178"
PACK_CODE = "5366"
QTY_PER_UNIT = Decimal("15")
TOTAL_QTY = Decimal("600")

FTL_TENDER_ID = "86e5fd7a-42e5-430f-94d7-216589748c9c"
FTL_ORDER_NUMBER = "96564"
FTL_CUSTOMER_PO = "4500309298"

LTL_TENDER_ID = "8dadc297-13db-4052-8737-299589b24241"
LTL_ORDER_NUMBER = "96399"
LTL_CUSTOMER_PO = "8510"
SHIP_DATE = date(2026, 5, 22)


def _tenant_settings() -> dict:
    return json.loads(_TENANT_SETTINGS_PATH.read_text(encoding="utf-8"))


def _workflow_state(*, tender_id: str) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="gelita",
        execution_id="test-run-calculate-tender-params",
        data={
            "tender_id": tender_id,
            "tenant_settings": _tenant_settings(),
        },
    )


def _ftl_bundle() -> dict:
    return {
        "tender": {
            "order_number": FTL_ORDER_NUMBER,
            "customer_name": "Test Customer",
            "shipping_date": SHIP_DATE,
            "delivery_date": SHIP_DATE,
            "metadata": {"po_number": FTL_CUSTOMER_PO},
            "delivery_address": None,
        },
        "products": [
            {
                "id": "tp-ftl-1",
                "tender_id": FTL_TENDER_ID,
                "product_name": "FORTIGEL B (US)",
                "order_quantity": Decimal("6720"),
                "price_per_unit": Decimal("20.66"),
                "pack_code_id": PACK_CODE_ID,
                "pack_code": PACK_CODE,
                "qty_per_unit": QTY_PER_UNIT,
                "total_qty": TOTAL_QTY,
                "metadata": {},
            }
        ],
    }


def _ltl_bundle() -> dict:
    def _line(
        product_name: str,
        order_quantity: str,
        price_per_unit: str = "22.18",
    ) -> dict:
        return {
            "product_name": product_name,
            "order_quantity": Decimal(order_quantity),
            "price_per_unit": Decimal(price_per_unit),
            "pack_code_id": PACK_CODE_ID,
            "pack_code": PACK_CODE,
            "qty_per_unit": QTY_PER_UNIT,
            "total_qty": TOTAL_QTY,
            "metadata": {},
        }

    return {
        "tender": {
            "order_number": LTL_ORDER_NUMBER,
            "customer_name": "Test Customer",
            "shipping_date": SHIP_DATE,
            "delivery_date": SHIP_DATE,
            "metadata": {"po_number": LTL_CUSTOMER_PO},
            "delivery_address": None,
        },
        "products": [
            _line("VERISOL® B (US)", "165"),
            _line("FORTIGEL B (US)", "315"),
            _line("FORTIBONE (US)", "315"),
        ],
    }


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_order_96564_ftl(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.read_order.return_value = _ftl_bundle()

    state = _workflow_state(tender_id=FTL_TENDER_ID)
    result = calculate_tender_params(state)

    assert result is state
    mock_svc.update_load_type.assert_called_once_with(
        tenant_id=TENANT_ID,
        tender_id=FTL_TENDER_ID,
        load_type="FTL",
    )

    tender = get_tender(result.data)
    assert tender is not None
    assert tender["load_type"] == "ftl"
    assert tender["order_number"] == FTL_ORDER_NUMBER
    assert tender["customer_po"] == FTL_CUSTOMER_PO
    assert tender["ship_date"] == "2026-05-22"

    products = tender["tender_products"]
    assert len(products) == 1
    line = products[0]
    assert line["pieces_count"] == "448"
    assert line["pallets_count"] == "12"
    assert line["product_value"] == Decimal("138835.20")

    ctx = build_tender_email_input_from_tender(tender)
    block = _ftl_products_block(ctx.products)
    assert "Pieces: 448" in block
    assert "Number of pallets: 12" in block
    assert f"Value: {_format_price(Decimal('138835.20'))}" in block
    assert _format_price(Decimal("138835.20")) == "138,835.20"


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_order_96399_ltl(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.read_order.return_value = _ltl_bundle()

    state = _workflow_state(tender_id=LTL_TENDER_ID)
    result = calculate_tender_params(state)

    mock_svc.update_load_type.assert_called_once_with(
        tenant_id=TENANT_ID,
        tender_id=LTL_TENDER_ID,
        load_type="LTL",
    )

    tender = get_tender(result.data)
    assert tender is not None
    assert tender["load_type"] == "ltl"
    assert tender["order_number"] == LTL_ORDER_NUMBER
    assert tender["customer_po"] == LTL_CUSTOMER_PO
    assert tender["ship_date"] == "2026-05-22"

    by_name = {p["product_name"]: p for p in tender["tender_products"]}
    assert len(by_name) == 3

    fortibone = by_name["FORTIBONE (US)"]
    assert fortibone["pieces_count"] == "21"
    assert fortibone["pallets_count"] == "1"
    assert fortibone["gross_weight_lbs"] == "743.00"

    fortigel = by_name["FORTIGEL B (US)"]
    assert fortigel["pieces_count"] == "21"
    assert fortigel["pallets_count"] == "1"
    assert fortigel["gross_weight_lbs"] == "743.00"

    verisol = by_name["VERISOL® B (US)"]
    assert verisol["pieces_count"] == "11"
    assert verisol["pallets_count"] == "1"
    assert verisol["gross_weight_lbs"] == "413.00"


def test_gelita_calculate_params_matches_db_order_96564() -> None:
    pieces, pallets, gross, value = gelita_calculate_params(
        order_quantity=Decimal("6720"),
        qty_per_unit=QTY_PER_UNIT,
        total_qty=TOTAL_QTY,
        pallet_weight_lb=50,
        unit_price=Decimal("20.66"),
    )
    assert pieces == 448
    assert pallets == 12
    assert gross == Decimal("15384.0")
    assert value == Decimal("138835.20")


def test_ftl_products_block_combines_same_product_name() -> None:
    products = (
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100.00",
            price="1,000.00",
        ),
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250.00",
            price="2,500.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert "Pieces: 25" in block
    assert "Number of pallets: 5" in block
    assert "Value: 3,500.00" in block
    assert "Gross weight" not in block


def test_ltl_products_block_combines_same_product_name() -> None:
    products = (
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100.00",
            price="1,000.00",
        ),
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250.00",
            price="2,500.00",
        ),
    )

    block = _ltl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert "Pieces: 25" in block
    assert "Number of pallets: 5" in block
    assert "Gross weight: ~350.00" in block
    assert "Value:" not in block


def test_products_block_keeps_different_product_names_separate() -> None:
    products = (
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100.00",
            price="1,000.00",
        ),
        TenderEmailProductLine(
            product_name="VERISOL B (US)",
            pack_code="5366",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250.00",
            price="2,500.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product:") == 2
    assert "Product: FORTIGEL B (US)" in block
    assert "Product: VERISOL B (US)" in block


def test_products_block_uses_trim_exact_product_name_matching() -> None:
    products = (
        TenderEmailProductLine(
            product_name="FORTIGEL B (US)",
            pack_code="5366",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100.00",
            price="1,000.00",
        ),
        TenderEmailProductLine(
            product_name=" FORTIGEL B (US) ",
            pack_code="5366",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250.00",
            price="2,500.00",
        ),
        TenderEmailProductLine(
            product_name="fortigel b (us)",
            pack_code="5366",
            pieces_count="20",
            pallets_count="4",
            gross_weight_lbs="300.00",
            price="3,000.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert "Pieces: 25" in block
    assert "Product: fortigel b (us)" in block
    assert "Pieces: 20" in block


@pytest.mark.parametrize(
    ("product_name", "order_quantity", "pieces", "pallets", "gross"),
    [
        ("FORTIBONE (US)", Decimal("315"), 21, 1, Decimal("743.0")),
        ("FORTIGEL B (US)", Decimal("315"), 21, 1, Decimal("743.0")),
        ("VERISOL® B (US)", Decimal("165"), 11, 1, Decimal("413.0")),
    ],
)
def test_gelita_calculate_params_matches_db_order_96399_lines(
    product_name: str,
    order_quantity: Decimal,
    pieces: int,
    pallets: int,
    gross: Decimal,
) -> None:
    del product_name
    got = gelita_calculate_params(
        order_quantity=order_quantity,
        qty_per_unit=QTY_PER_UNIT,
        total_qty=TOTAL_QTY,
        pallet_weight_lb=50,
        unit_price=Decimal("22.18"),
    )
    assert got[:3] == (pieces, pallets, gross)
