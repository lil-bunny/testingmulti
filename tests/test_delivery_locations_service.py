"""Tests for delivery location lookup by ``delviery`` number."""

from __future__ import annotations

from typing import Any

from app.domain.delivery_locations import DeliveryLocationsIndex
from app.services.delivery_locations_service import DeliveryLocationsService


def _fixture_rows() -> list[dict[str, Any]]:
    return [
        {
            "BP #": "41000000",
            "delviery": "41000000",
            "City": "NORTH RICHLAND HILLS          ",
        },
        {
            "BP #": "41000100",
            "delviery": "41000100",
            "City": "SIOUX CITY",
        },
    ]


def _service() -> DeliveryLocationsService:
    return DeliveryLocationsService(rows_provider=_fixture_rows)


def test_lookup_hit() -> None:
    svc = _service()

    row = svc.lookup("41000100")

    assert row is not None
    assert row["delviery"] == "41000100"
    assert row["City"] == "SIOUX CITY"


def test_lookup_miss() -> None:
    svc = _service()

    assert svc.lookup("99999999") is None


def test_lookup_normalizes_whitespace_in_query() -> None:
    svc = _service()

    row = svc.lookup("  41000100  ")

    assert row is not None
    assert row["City"] == "SIOUX CITY"


def test_delivery_locations_index_build_and_lookup() -> None:
    index = DeliveryLocationsIndex(
        [
            {"delviery": "41000100", "City": "SIOUX CITY"},
            {"delviery": "41000100", "City": "DUPLICATE"},
        ]
    )
    row = index.lookup("41000100")
    assert row is not None
    assert row["City"] == "SIOUX CITY"


def test_lookup_cleans_row_values() -> None:
    svc = _service()

    row = svc.lookup("41000000")

    assert row is not None
    assert row["City"] == "NORTH RICHLAND HILLS"


def test_rows_provider_invoked_once_per_service() -> None:
    calls = {"n": 0}

    def provider() -> list[dict[str, Any]]:
        calls["n"] += 1
        return _fixture_rows()

    svc = DeliveryLocationsService(rows_provider=provider)
    svc.lookup("41000100")
    svc.lookup("41000000")
    svc.lookup("nope")

    assert calls["n"] == 1
