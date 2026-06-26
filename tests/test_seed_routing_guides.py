"""Unit tests for routing guide CSV seed parsing."""

from __future__ import annotations

from scripts.seed_routing_guides import routing_guide_row_from_csv_row


def test_routing_guide_row_from_csv_row_us_zip_and_location() -> None:
    payload = routing_guide_row_from_csv_row(
        {
            "Business partner": "Pharmavite",
            "City": "New Albany",
            "State": "OH",
            "Zip": "43031",
            "Plan A": "Fitzmark",
        },
        carrier_emails={"Fitzmark": "fitz@example.com"},
    )
    assert payload is not None
    assert payload["customer_name"] == "Pharmavite"
    assert payload["city"] == "New Albany"
    assert payload["state"] == "OH"
    assert payload["zipcode"] == "43031"
    assert payload["carriers"] == {
        "a": {"name": "Fitzmark", "email": "fitz@example.com"},
    }


def test_routing_guide_row_from_csv_row_canadian_zip_preserves_space() -> None:
    payload = routing_guide_row_from_csv_row(
        {
            "Business partner": "Catalent Canada",
            "City": "Strathroy",
            "State": "ON",
            "Zip": "N7G 3H8",
            "Plan A": "Fitzmark",
        },
    )
    assert payload is not None
    assert payload["zipcode"] == "N7G 3H8"
    assert payload["city"] == "Strathroy"
    assert payload["state"] == "ON"


def test_routing_guide_row_from_csv_row_zip_plus_four_truncates_to_five() -> None:
    payload = routing_guide_row_from_csv_row(
        {
            "Business partner": "IVC",
            "City": "Greenville",
            "State": "SC",
            "Zip": "29607-4197",
            "Plan A": "Fitzmark",
        },
    )
    assert payload is not None
    assert payload["zipcode"] == "29607"
