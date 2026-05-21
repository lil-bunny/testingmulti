"""Tests for delivery_address JSON mapping and resolve."""

from __future__ import annotations

from app.domain.delivery_address import (
    delivery_address_from_location_row,
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
        return "Iowa"

    out = delivery_address_from_location_row(
        _sioux_city_row(), state_resolver=resolver
    )

    assert out["state"] == "Iowa"
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
        "41000100", index, state_resolver=lambda _c, _p: "Iowa"
    )
    assert out is not None
    assert out["state"] == "Iowa"
