"""Unit tests for Gelita routing-guide policy."""

from __future__ import annotations

from app.domain.gelita.routing_guide import (
    gelita_normalize_lane_zip,
    gelita_partner_matches_source_label,
    gelita_plan_carrier_for_attempt,
    gelita_select_lane,
)
from app.domain.routing_guide import RoutingGuideRow
from app.domain.routing_guide.types import PlanCarrierSlot

_SAMPLE_CARRIERS = {
    "a": PlanCarrierSlot(name="Schneider", email="carrier@example.com"),
    "b": PlanCarrierSlot(name="Axle", email="axle@example.com"),
    "c": PlanCarrierSlot(name="J.B. Hunt", email="jb@example.com"),
}


def test_gelita_normalize_lane_zip_five_digit_and_zip_plus_four() -> None:
    assert gelita_normalize_lane_zip("29607-4197") == "29607"
    assert gelita_normalize_lane_zip("83402-1234") == "83402"
    assert gelita_normalize_lane_zip(" 83402 ") == "83402"
    assert gelita_normalize_lane_zip("H9P 2Y1") == "H9P 2Y1"
    assert gelita_normalize_lane_zip("N7G 3H8") == "N7G 3H8"


def test_gelita_partner_matches_source_label_exact_and_alias() -> None:
    assert gelita_partner_matches_source_label(
        source_partner_label="Pharmavite",
        customer_name="Pharmavite",
    )
    assert gelita_partner_matches_source_label(
        source_partner_label="GELITA MEX",
        customer_name="G-MEX",
        customer_aliases=["GELITA MEX", "GELITA MEXICO"],
    )


def test_gelita_select_lane_unique_zip_skips_partner_check() -> None:
    row = RoutingGuideRow(
        id="1",
        customer_name="Catalent",
        zipcode="46168",
        city="",
        state="",
        metadata={},
        customer_aliases=[],
        carriers=_SAMPLE_CARRIERS,
    )
    assert gelita_select_lane([row], source_partner_label="") == row


def test_gelita_select_lane_multi_zip_requires_partner_match() -> None:
    rows = [
        RoutingGuideRow(
            id="1",
            customer_name="Catalent USA",
            zipcode="46168",
            city="",
            state="",
            metadata={},
            customer_aliases=[],
            carriers={},
        ),
        RoutingGuideRow(
            id="2",
            customer_name="Lonza",
            zipcode="46168",
            city="",
            state="",
            metadata={},
            customer_aliases=[],
            carriers={},
        ),
    ]
    assert gelita_select_lane(rows, source_partner_label="LONZA") is not None
    assert gelita_select_lane(rows, source_partner_label="UNKNOWN") is None


def test_gelita_plan_carrier_for_attempt_reads_slot_carriers() -> None:
    assert gelita_plan_carrier_for_attempt(_SAMPLE_CARRIERS, 1) == (
        "Schneider",
        "carrier@example.com",
    )
    assert gelita_plan_carrier_for_attempt(_SAMPLE_CARRIERS, 2) == (
        "Axle",
        "axle@example.com",
    )
    assert gelita_plan_carrier_for_attempt(_SAMPLE_CARRIERS, 3) == (
        "J.B. Hunt",
        "jb@example.com",
    )
