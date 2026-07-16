"""Unit tests for Gelita partial-pallet dimension scaling."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.domain.load_tendering_state import get_tender, set_tender, tender_from_read_order
from app.domain.state import WorkflowState
from app.tools.gelita.pallet_dims import adjust_unit_dims_for_partial_pallet
from app.tools.tender_email import build_tender_email_input_from_tender, _ltl_products_block
from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params
from tests.fixtures.tenant_settings import load_tenant_settings_dev
from tests.test_calculate_tender_params import (
    TENANT_ID,
    _sample_delivery_address,
    _tenant_settings,
)

PACK_5318_UNIT_DIMS = '48"x41"x60"'
PACK_5318_PALLET_DIMS = '48"x40"x5"'
PACK_6310_UNIT_DIMS = '48"x41"x51"'


@pytest.mark.parametrize(
    ("pieces", "pallets", "units_per_pallet", "expected"),
    [
        (25, 1, 50, '48"x41"x32"'),
        (50, 1, 50, PACK_5318_UNIT_DIMS),
        (25, 2, 50, PACK_5318_UNIT_DIMS),
        (40, 1, 40, PACK_6310_UNIT_DIMS),
        (21, 2, 40, PACK_6310_UNIT_DIMS),
    ],
)
def test_adjust_unit_dims_for_partial_pallet(
    pieces: int,
    pallets: int,
    units_per_pallet: int,
    expected: str,
) -> None:
    result = adjust_unit_dims_for_partial_pallet(
        unit_dims=PACK_5318_UNIT_DIMS
        if units_per_pallet == 50
        else PACK_6310_UNIT_DIMS,
        pallet_dims=PACK_5318_PALLET_DIMS,
        pieces_count=pieces,
        pallets_count=pallets,
        units_per_pallet=units_per_pallet,
    )
    assert result == expected


def test_adjust_unit_dims_returns_original_when_pallet_dims_missing() -> None:
    assert (
        adjust_unit_dims_for_partial_pallet(
            unit_dims=PACK_5318_UNIT_DIMS,
            pallet_dims="",
            pieces_count=25,
            pallets_count=1,
            units_per_pallet=50,
        )
        == PACK_5318_UNIT_DIMS
    )


@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_calculate_tender_params_scales_dims_for_single_partial_pallet(
    mock_tender_service_cls: object,
) -> None:
    mock_tender_service_cls.return_value.update_load_type = lambda **_: None

    state = WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="gelita",
        execution_id="test-partial-pallet-dims",
        data={
            "tender_id": "tender-97319",
            "tenant_settings": _tenant_settings(),
        },
    )
    bundle = {
        "tender": {
            "order_number": "97319",
            "customer_name": "Test Customer",
            "shipping_date": "2026-07-08",
            "delivery_date": "2026-07-08",
            "metadata": {"po_number": "PO-26123C"},
            "delivery_address": _sample_delivery_address(),
        },
        "products": [
            {
                "product_name": "150 BL TYPE B NF SRM FREE BONE GELATIN",
                "order_quantity": Decimal("500"),
                "price_per_unit": Decimal("32.81"),
                "pack_code_id": "pack-5318",
                "pack_code": "5318",
                "qty_per_unit": Decimal("20"),
                "total_qty": Decimal("1000"),
                "units_per_pallet": Decimal("50"),
                "unit_dims": PACK_5318_UNIT_DIMS,
                "pallet_dims": PACK_5318_PALLET_DIMS,
                "pallet_type": "4-way wood",
                "pack_type": "bag",
                "pack_type_weight": Decimal("0.7"),
                "weight_unit": "kg",
                "metadata": {},
            }
        ],
    }
    set_tender(
        state.data,
        tender_from_read_order(
            {"tender": bundle["tender"], "products": bundle["products"]},
            None,
        ),
    )

    calculate_tender_params(state)

    tender = get_tender(state.data)
    assert tender is not None
    line = tender["tender_products"][0]
    assert line["pieces_count"] == "25"
    assert line["pallets_count"] == "1"
    assert line["unit_dims"] == '48"x41"x32"'

    ctx = build_tender_email_input_from_tender(tender)
    block = _ltl_products_block(ctx.products, order_gross_weight_lbs=ctx.gross_weight_lbs)
    assert 'Number of pallets: 1 pallets ~ 48&quot;x41&quot;x32&quot;' in block
