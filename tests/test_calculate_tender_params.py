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

from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.load_tendering_state import get_tender
from app.domain.state import WorkflowState
from app.tools.tender_email import (
    TenderEmailProductLine,
    _format_price,
    _ftl_products_block,
    _ltl_products_block,
    build_tender_email_input_from_tender,
)
from app.models.weight_unit import WeightUnit
from app.workflows.nodes.gelita.calculate_tender_params import (
    _round_pallet_count,
    calculate_tender_params,
    gelita_calculate_params,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev

# Live DB snapshot (order_number → tender / products / pack_codes)
TENANT_ID = "aadc75f4-3f79-45d7-84c3-aa778e226e92"
PACK_CODE_ID = "9d579b89-2280-4fb0-8f1b-12acf9c5f178"
PACK_CODE = "5366"
QTY_PER_UNIT = Decimal("15")
TOTAL_QTY = Decimal("600")
UNIT_DIMS = '48"x40"x5"'

FTL_TENDER_ID = "86e5fd7a-42e5-430f-94d7-216589748c9c"
FTL_ORDER_NUMBER = "96564"
FTL_CUSTOMER_PO = "4500309298"

LTL_TENDER_ID = "8dadc297-13db-4052-8737-299589b24241"
LTL_ORDER_NUMBER = "96399"
LTL_CUSTOMER_PO = "8510"
SHIP_DATE = date(2026, 5, 22)


def _email_product_line(
    *,
    product_name: str,
    pieces_count: str,
    pallets_count: str,
    gross_weight_lbs: str,
    price: str = "",
    pack_code: str = PACK_CODE,
    qty_per_unit: str = "15",
    weight_unit: str = "kg",
    unit_dims: str = UNIT_DIMS,
) -> TenderEmailProductLine:
    return TenderEmailProductLine(
        product_name=product_name,
        pack_code=pack_code,
        pieces_count=pieces_count,
        qty_per_unit=qty_per_unit,
        weight_unit=weight_unit,
        pallets_count=pallets_count,
        unit_dims=unit_dims,
        gross_weight_lbs=gross_weight_lbs,
        price=price,
    )


def _tenant_settings() -> dict:
    return load_tenant_settings_dev("gelita")


def _sample_delivery_address() -> dict[str, str]:
    return {
        "name": "Test Customer",
        "address1": "123 Main St",
        "city": "SIOUX CITY",
        "state": "IA",
        "postal_code": "51105",
        "country": "US",
    }


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
            "delivery_address": _sample_delivery_address(),
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
                "pallet_type": "4-way wood",
                "unit_dims": UNIT_DIMS,
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
            "pallet_type": "4-way wood",
            "unit_dims": UNIT_DIMS,
            "metadata": {},
        }

    return {
        "tender": {
            "order_number": LTL_ORDER_NUMBER,
            "customer_name": "Test Customer",
            "shipping_date": SHIP_DATE,
            "delivery_date": SHIP_DATE,
            "metadata": {"po_number": LTL_CUSTOMER_PO},
            "delivery_address": _sample_delivery_address(),
        },
        "products": [
            _line("VERISOL® B (US)", "165"),
            _line("FORTIGEL B (US)", "315"),
            _line("FORTIBONE (US)", "315"),
        ],
    }


def test_calculate_tender_params_missing_tenant_id_returns_error_code() -> None:
    state = WorkflowState(
        tenant_id="",
        tenant_slug="gelita",
        execution_id="test-run-calculate-tender-params",
        data={
            "tender_id": FTL_TENDER_ID,
            "tenant_settings": _tenant_settings(),
        },
    )

    result = calculate_tender_params(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_TENANT_ID
    assert error["category"] == BusinessError.CATEGORY.value
    assert error["message"] == BusinessError.MISSING_TENANT_ID.description


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_missing_delivery_address_returns_error_code(
    mock_svc_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    bundle = _ftl_bundle()
    bundle["tender"]["delivery_address"] = None
    mock_svc.read_order.return_value = bundle

    state = _workflow_state(tender_id=FTL_TENDER_ID)
    state.data["tender"] = {
        "order_number": FTL_ORDER_NUMBER,
        "delivery_address_code": "41000100",
    }
    result = calculate_tender_params(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_DELIVERY_ADDRESS.value
    assert error["category"] == BusinessError.CATEGORY.value
    assert error["message"] == format_error_message(
        BusinessError.MISSING_DELIVERY_ADDRESS, del_code="41000100"
    )
    assert result["data"]["delivery_address_code"] == "41000100"
    mock_svc.update_load_type.assert_not_called()


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_missing_customer_name_returns_error_code(
    mock_svc_cls: MagicMock,
) -> None:
    from app.domain.delivery_address import (
        CUSTOMER_NAME_PLACEHOLDER,
        CUSTOMER_NAME_SOURCE_UNKNOWN,
    )

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    bundle = _ftl_bundle()
    bundle["tender"]["customer_name"] = CUSTOMER_NAME_PLACEHOLDER
    bundle["tender"]["metadata"] = {"customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN}
    mock_svc.read_order.return_value = bundle

    state = _workflow_state(tender_id=FTL_TENDER_ID)
    state.data["tender"] = {
        "order_number": FTL_ORDER_NUMBER,
        "delivery_address_code": "41000100",
    }
    result = calculate_tender_params(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_CUSTOMER_NAME.value
    assert error["category"] == BusinessError.CATEGORY.value
    assert error["message"] == format_error_message(
        BusinessError.MISSING_CUSTOMER_NAME, del_code="41000100"
    )
    assert result["data"]["delivery_address_code"] == "41000100"
    mock_svc.update_load_type.assert_not_called()


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_missing_unit_dims_returns_error_code(
    mock_svc_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    bundle = _ftl_bundle()
    bundle["products"][0].pop("unit_dims")
    mock_svc.read_order.return_value = bundle

    state = _workflow_state(tender_id=FTL_TENDER_ID)
    result = calculate_tender_params(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_UNIT_DIMS
    assert error["category"] == BusinessError.CATEGORY.value
    assert error["message"] == format_error_message(
        BusinessError.MISSING_UNIT_DIMS, pack_code=PACK_CODE
    )
    mock_svc.update_load_type.assert_not_called()


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
    assert tender["gross_weight_lbs"] == "15,415"

    ctx = build_tender_email_input_from_tender(tender)
    block = _ftl_products_block(
        ctx.products,
        order_gross_weight_lbs=ctx.gross_weight_lbs,
        order_value=ctx.order_value,
    )
    assert "Gross weight: ~15,415 pounds" in block
    assert "Pieces: 448 bags @ 15kg each" in block
    assert "Number of pallets: 12 pallets ~ 48&quot;x40&quot;x5&quot;" in block
    assert block.count("Value:") == 1
    assert f"Value: {_format_price(Decimal('138835.20'))}" in block
    assert block.index("Value:") < block.index("Product:")
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
    assert fortibone["gross_weight_lbs"] == "745"

    fortigel = by_name["FORTIGEL B (US)"]
    assert fortigel["pieces_count"] == "21"
    assert fortigel["pallets_count"] == "1"
    assert fortigel["gross_weight_lbs"] == "745"

    verisol = by_name["VERISOL® B (US)"]
    assert verisol["pieces_count"] == "11"
    assert verisol["pallets_count"] == "1"
    assert verisol["gross_weight_lbs"] == "414"
    assert tender["gross_weight_lbs"] == "1,904"

    ctx = build_tender_email_input_from_tender(tender)
    block = _ltl_products_block(
        ctx.products,
        order_gross_weight_lbs=ctx.gross_weight_lbs,
    )
    assert block.count("Gross weight:") == 1
    assert "Gross weight: ~1,904 pounds" in block
    assert "Pieces: 21 bags @ 15kg each" in block


@pytest.mark.parametrize(
    ("pallets_raw", "expected"),
    [
        (Decimal("3.04"), 3),
        (Decimal("3.05"), 3),
        (Decimal("3.06"), 4),
        (Decimal("11.2"), 12),
        (Decimal("12.05"), 12),
        (Decimal("12.06"), 13),
        (Decimal("0.525"), 1),
    ],
)
def test_round_pallet_count_qa_tolerance(pallets_raw: Decimal, expected: int) -> None:
    assert _round_pallet_count(pallets_raw) == expected


def test_gelita_calculate_params_uses_european_pallet_weight() -> None:
    pieces, pallets, gross, _value = gelita_calculate_params(
        order_quantity=Decimal("600"),
        qty_per_unit=QTY_PER_UNIT,
        total_qty=TOTAL_QTY,
        pallet_weight_lb=56,
        unit_price=None,
    )
    assert pieces == 40
    assert pallets == 1
    assert gross == Decimal("1379")


def test_gelita_calculate_params_kg_converts_to_lbs() -> None:
    pieces, pallets, gross, _value = gelita_calculate_params(
        order_quantity=Decimal("1000"),
        qty_per_unit=Decimal("40"),
        total_qty=Decimal("2000"),
        pallet_weight_lb=50,
        unit_price=None,
        weight_unit=WeightUnit.KG,
    )
    assert pieces == 25
    assert pallets == 1
    assert gross == Decimal("2255")


def test_gelita_calculate_params_lbs_skips_conversion() -> None:
    pieces, pallets, gross, _value = gelita_calculate_params(
        order_quantity=Decimal("1000"),
        qty_per_unit=Decimal("40"),
        total_qty=Decimal("2000"),
        pallet_weight_lb=50,
        unit_price=None,
        weight_unit=WeightUnit.LBS,
    )
    assert pieces == 25
    assert pallets == 1
    assert gross == Decimal("1050")


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
    assert gross == Decimal("15415")
    assert value == Decimal("138835.20")


def test_ftl_products_block_combines_same_product_name() -> None:
    products = (
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100",
            price="1,000.00",
        ),
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250",
            price="2,500.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert "Pieces: 25 bags @ 15kg each" in block
    assert "Number of pallets: 5 pallets ~ 48&quot;x40&quot;x5&quot;" in block
    assert block.count("Value:") == 1
    assert "Value: 3,500.00" in block
    assert block.index("Value:") < block.index("Product: FORTIGEL B (US)")
    assert block.count("Gross weight:") == 1
    assert "Gross weight: ~350 pounds" in block


def test_ltl_products_block_combines_same_product_name() -> None:
    products = (
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100",
            price="1,000.00",
        ),
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250",
            price="2,500.00",
        ),
    )

    block = _ltl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert block.count("Gross weight:") == 1
    assert "Pieces: 25 bags @ 15kg each" in block
    assert "Number of pallets: 5 pallets ~ 48&quot;x40&quot;x5&quot;" in block
    assert "Gross weight: ~350 pounds" in block
    assert block.index("Gross weight:") < block.index("Product: FORTIGEL B (US)")
    assert "Value:" not in block


def test_products_block_keeps_different_product_names_separate() -> None:
    products = (
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100",
            price="1,000.00",
        ),
        _email_product_line(
            product_name="VERISOL B (US)",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250",
            price="2,500.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product:") == 2
    assert block.count("Gross weight:") == 1
    assert block.count("Value:") == 1
    assert "Value: 3,500.00" in block
    assert "Gross weight: ~350 pounds" in block
    assert "Product: FORTIGEL B (US)" in block
    assert "Product: VERISOL B (US)" in block


def test_products_block_uses_trim_exact_product_name_matching() -> None:
    products = (
        _email_product_line(
            product_name="FORTIGEL B (US)",
            pieces_count="10",
            pallets_count="2",
            gross_weight_lbs="100",
            price="1,000.00",
        ),
        _email_product_line(
            product_name=" FORTIGEL B (US) ",
            pieces_count="15",
            pallets_count="3",
            gross_weight_lbs="250",
            price="2,500.00",
        ),
        _email_product_line(
            product_name="fortigel b (us)",
            pieces_count="20",
            pallets_count="4",
            gross_weight_lbs="300",
            price="3,000.00",
        ),
    )

    block = _ftl_products_block(products)

    assert block.count("Product: FORTIGEL B (US)") == 1
    assert "Pieces: 25 bags @ 15kg each" in block
    assert "Product: fortigel b (us)" in block
    assert "Pieces: 20 bags @ 15kg each" in block


def test_format_bags_line_uses_lbs_weight_unit() -> None:
    products = (
        _email_product_line(
            product_name="Gelatin",
            pieces_count="25",
            pallets_count="1",
            gross_weight_lbs="1050",
            qty_per_unit="50",
            weight_unit="lbs",
        ),
    )
    block = _ltl_products_block(products)
    assert "Pieces: 25 bags @ 50lbs each" in block


@pytest.mark.parametrize(
    ("product_name", "order_quantity", "pieces", "pallets", "gross"),
    [
        ("FORTIBONE (US)", Decimal("315"), 21, 1, Decimal("745")),
        ("FORTIGEL B (US)", Decimal("315"), 21, 1, Decimal("745")),
        ("VERISOL® B (US)", Decimal("165"), 11, 1, Decimal("414")),
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
