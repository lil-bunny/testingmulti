"""Tests for delivery_address JSON mapping and resolve."""

from __future__ import annotations

import pytest

from app.domain.delivery_address import (
    CUSTOMER_NAME_PLACEHOLDER,
    CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION,
    CUSTOMER_NAME_SOURCE_UNKNOWN,
    delivery_address_from_location_row,
    format_usps_mailing_address,
    is_unresolved_customer_name,
    resolve_delivery_address,
)
from app.domain.delivery_locations import DeliveryLocationsIndex


def _sioux_city_row() -> dict:
    return {
        "delviery": "41000100",
        "Name": "CARRIER CLAIMS ABF FREIGHT",
        "Name2": None,
        "Street": "1420 STEUBEN STREET",
        "Street 2": None,
        "Zip Code": "51105",
        "City": "SIOUX CITY",
        "country name": "U.S.A.",
    }


def test_delivery_address_from_location_row() -> None:
    out = delivery_address_from_location_row(_sioux_city_row())
    assert out == {
        "name": "CARRIER CLAIMS ABF FREIGHT",
        "name2": None,
        "address1": "1420 STEUBEN STREET",
        "address2": None,
        "city": "SIOUX CITY",
        "state": "",
        "postal_code": "51105",
        "country": "U.S.A.",
    }


def test_delivery_address_empty_name_and_state() -> None:
    row = {
        "Name": None,
        "Name2": "  ",
        "Street": "1 Main",
        "Street 2": "",
        "City": "X",
        "Zip Code": "1",
        "country name": "US",
    }
    out = delivery_address_from_location_row(row)
    assert out["name"] == ""
    assert out["name2"] is None
    assert out["address2"] is None
    assert out["state"] == ""


def test_delivery_address_normalizes_pandas_nan_to_none() -> None:
    """Blank xlsx cells arrive as float('nan') from pandas; must not become 'nan' strings."""
    row = {
        "Name": "OK",
        "Name2": float("nan"),
        "Street": float("nan"),
        "Street 2": float("nan"),
        "City": "X",
        "Zip Code": "1",
        "country name": "US",
    }
    out = delivery_address_from_location_row(row)
    assert out["name"] == "OK"
    assert out["name2"] is None
    assert out["address1"] == ""
    assert out["address2"] is None


def test_delivery_address_normalizes_literal_nan_string_to_none() -> None:
    """Some sources serialize NaN as the literal string 'nan'; treat as missing."""
    row = {
        "Name": "OK",
        "Name2": "nan",
        "Street": "NaN",
        "Street 2": " nan ",
        "City": "X",
        "Zip Code": "1",
        "country name": "US",
    }
    out = delivery_address_from_location_row(row)
    assert out["name2"] is None
    assert out["address1"] == ""
    assert out["address2"] is None


def test_resolve_delivery_address_hit() -> None:
    index = DeliveryLocationsIndex([_sioux_city_row()])
    out = resolve_delivery_address("41000100", index)
    assert out is not None
    assert out["city"] == "SIOUX CITY"


def test_resolve_delivery_address_miss_and_blank() -> None:
    index = DeliveryLocationsIndex([_sioux_city_row()])
    assert resolve_delivery_address("99999999", index) is None
    assert resolve_delivery_address("", index) is None
    assert resolve_delivery_address("41000100", None) is None


def test_delivery_address_state_resolver_fills_state() -> None:
    seen: list[tuple[str | None, object]] = []

    def resolver(country: str | None, postal: object) -> str | None:
        seen.append((country, postal))
        return "IA"

    out = delivery_address_from_location_row(
        _sioux_city_row(), state_resolver=resolver
    )

    assert out["state"] == "IA"
    assert seen == [("U.S.A.", "51105")]


def test_delivery_address_state_resolver_returning_none_keeps_empty() -> None:
    out = delivery_address_from_location_row(
        _sioux_city_row(), state_resolver=lambda _c, _p: None
    )
    assert out["state"] == ""


def test_delivery_address_state_resolver_returning_blank_keeps_empty() -> None:
    out = delivery_address_from_location_row(
        _sioux_city_row(), state_resolver=lambda _c, _p: "   "
    )
    assert out["state"] == ""


def test_resolve_delivery_address_threads_state_resolver_through() -> None:
    index = DeliveryLocationsIndex([_sioux_city_row()])
    out = resolve_delivery_address(
        "41000100", index, state_resolver=lambda _c, _p: "IA"
    )
    assert out is not None
    assert out["state"] == "IA"


def _minimal_row(*, city: str, zip_code: str = "78045", country: str = "U.S.A.") -> dict:
    return {
        "Name": "TEST",
        "Street": "1 Main",
        "City": city,
        "Zip Code": zip_code,
        "country name": country,
    }


@pytest.mark.parametrize(
    ("city_cell", "expected_city", "expected_state", "resolver_called"),
    [
        ("LAREDO, TX", "LAREDO", "TX", False),
        ("LERMA, EDO", "LERMA", "EDO", False),
        ("MILLS RIVER", "MILLS RIVER", "NC", True),
        ("SIOUX CITY", "SIOUX CITY", "IA", True),
        ("FOO,", "FOO", "IA", True),
    ],
)
def test_delivery_address_city_state_from_q_column(
    city_cell: str,
    expected_city: str,
    expected_state: str,
    resolver_called: bool,
) -> None:
    seen: list[tuple[str | None, object]] = []

    def resolver(country: str | None, postal: object) -> str | None:
        seen.append((country, postal))
        return expected_state

    row = _minimal_row(city=city_cell)
    out = delivery_address_from_location_row(row, state_resolver=resolver)

    assert out["city"] == expected_city
    assert out["state"] == expected_state
    if resolver_called:
        assert seen == [("U.S.A.", "78045")]
    else:
        assert seen == []


def test_format_usps_mailing_address_prefers_stored_state() -> None:
    addr = {
        "city": "LAREDO",
        "state": "TX",
        "postal_code": "78045",
        "country": "U.S.A.",
    }
    formatted = format_usps_mailing_address(addr)
    assert formatted == "LAREDO TX 78045"


@pytest.mark.parametrize(
    ("tender", "expected"),
    [
        (
            {
                "customer_name": CUSTOMER_NAME_PLACEHOLDER,
                "metadata": {"customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN},
            },
            True,
        ),
        (
            {
                "customer_name": CUSTOMER_NAME_PLACEHOLDER,
                "metadata": {},
            },
            True,
        ),
        (
            {
                "customer_name": "MERICAL",
                "metadata": {"customer_name_source": CUSTOMER_NAME_SOURCE_DELIVERY_LOCATION},
            },
            False,
        ),
        (
            {
                "customer_name": "MERICAL",
                "metadata": {"customer_name_source": CUSTOMER_NAME_SOURCE_UNKNOWN},
            },
            True,
        ),
    ],
)
def test_is_unresolved_customer_name(tender: dict, expected: bool) -> None:
    assert is_unresolved_customer_name(tender) is expected
