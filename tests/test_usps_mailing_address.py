"""Tests for USPS mailing-block formatting of structured address JSON."""

from __future__ import annotations

import app.configs.gelita_config as gelita_config
from app.domain.delivery_address import (
    delivery_address_from_location_row,
    format_usps_mailing_address,
)


def test_format_gelita_pickup_from_config() -> None:
    out = format_usps_mailing_address(gelita_config.GELITA_PICKUP_ADDRESS)
    assert out == (
        "GELITA USA\n"
        "2445 PORT NEAL INDUSTRIAL RD\n"
        "SERGEANT BLUFF IA 51054"
    )


def test_format_delivery_from_ingest_shaped_json() -> None:
    addr = delivery_address_from_location_row(
        {
            "Name": "CARRIER CLAIMS ABF FREIGHT",
            "Name2": None,
            "Street": "1420 STEUBEN STREET",
            "Street 2": None,
            "City": "SIOUX CITY",
            "Zip Code": "51105",
            "country name": "U.S.A.",
        },
        state_resolver=lambda _c, _p: "IA",
    )
    out = format_usps_mailing_address(addr)
    assert out == (
        "CARRIER CLAIMS ABF FREIGHT\n"
        "1420 STEUBEN STREET\n"
        "SIOUX CITY IA 51105"
    )


def test_format_includes_name2_and_address2_lines() -> None:
    out = format_usps_mailing_address(
        {
            "name": "ACME",
            "name2": "ATTN RECEIVING",
            "address1": "1 MAIN ST",
            "address2": "SUITE 2",
            "city": "Austin",
            "state": "TX",
            "postal_code": "78701",
            "country": "U.S.A.",
        }
    )
    assert out.splitlines() == [
        "ACME",
        "ATTN RECEIVING",
        "1 MAIN ST",
        "SUITE 2",
        "AUSTIN TX 78701",
    ]


def test_format_none_or_empty_returns_blank() -> None:
    assert format_usps_mailing_address(None) == ""
    assert format_usps_mailing_address({}) == ""
