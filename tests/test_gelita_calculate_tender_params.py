"""Tests for Gelita ``calculate_tender_params`` pallet rounding and gross weight."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.domain.state import WorkflowState
from app.models.load_type import LoadType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_TENDER_CALCULATE_CFG = {
    "pallet_weight_lbs": 50.0,
    "pallet_threshold": 8,
    "gelita_pickup_address": {
        "name": "GELITA USA",
        "street": "1 Plant Rd",
        "city": "SIOUX CITY",
        "state": "IA",
        "zip": "51111",
        "country": "US",
    },
}


def _state() -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={"tender_id": TENDER_UUID},
    )


def _tender_row(
    *,
    order_quantity: int | float,
    qty_per_unit: int,
    total_qty: int,
) -> dict:
    return {
        "pack_code_id": 1,
        "order_quantity": order_quantity,
        "qty_per_unit": qty_per_unit,
        "total_qty": total_qty,
        "pack_code": "5366",
        "order_number": "93795",
        "product_name": "VERISOL B (US)",
        "shipping_date": None,
        "delivery_date": None,
        "delivery_address": None,
        "metadata": {},
    }


@patch(
    "app.workflows.nodes.gelita.calculate_tender_params.action_settings",
    return_value=_TENDER_CALCULATE_CFG,
)
@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
@pytest.mark.parametrize(
    (
        "order_quantity",
        "total_qty",
        "expected_pallets",
        "expected_gross",
        "expected_load_type",
    ),
    [
        (1635, 600, "3", "3,747.00", LoadType.LTL),
        (19000, 1000, "19", "42,750.00", LoadType.FTL),
        (15, 600, "1", "83.00", LoadType.LTL),
    ],
)
def test_pallets_ceiled_for_gross_weight_and_load_type(
    mock_svc_cls: MagicMock,
    _mock_action_settings: MagicMock,
    order_quantity: int,
    total_qty: int,
    expected_pallets: str,
    expected_gross: str,
    expected_load_type: LoadType,
) -> None:
    from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.read_row.return_value = _tender_row(
        order_quantity=order_quantity,
        qty_per_unit=15,
        total_qty=total_qty,
    )

    state = _state()
    result = calculate_tender_params(state)

    assert result.data.get("tender_calc_error") is None
    assert result.data["pallets_count"] == expected_pallets
    assert result.data["gross_weight_lbs"] == expected_gross
    mock_svc.update_load_type.assert_called_once()
    assert mock_svc.update_load_type.call_args.kwargs["load_type"] == expected_load_type


@patch(
    "app.workflows.nodes.gelita.calculate_tender_params.action_settings",
    return_value=_TENDER_CALCULATE_CFG,
)
@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_pallets_ceiling_can_switch_to_ftl(
    mock_svc_cls: MagicMock,
    _mock_action_settings: MagicMock,
) -> None:
    from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    # 7201 kg / 800 = 9.00125 -> 10 pallets (> threshold 8)
    mock_svc.read_row.return_value = _tender_row(
        order_quantity=7201,
        qty_per_unit=800,
        total_qty=800,
    )

    state = _state()
    calculate_tender_params(state)

    assert state.data["pallets_count"] == "10"
    assert mock_svc.update_load_type.call_args.kwargs["load_type"] == LoadType.FTL


@patch(
    "app.workflows.nodes.gelita.calculate_tender_params.action_settings",
    return_value=_TENDER_CALCULATE_CFG,
)
@patch("app.workflows.nodes.gelita.calculate_tender_params.TenderService")
def test_gross_weight_uses_ceiled_pallets_not_raw_fraction(
    mock_svc_cls: MagicMock,
    _mock_action_settings: MagicMock,
) -> None:
    from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.read_row.return_value = _tender_row(
        order_quantity=1635,
        qty_per_unit=15,
        total_qty=600,
    )

    state = _state()
    calculate_tender_params(state)

    raw_pallets = Decimal("1635") / Decimal("600")
    raw_gross = (Decimal("1635") * Decimal("2.2")) + (Decimal("50") * raw_pallets)
    ceiled_gross = (Decimal("1635") * Decimal("2.2")) + (Decimal("50") * Decimal("3"))

    assert state.data["gross_weight_lbs"] == f"{ceiled_gross:,.2f}"
    assert state.data["gross_weight_lbs"] != f"{raw_gross:,.2f}"
