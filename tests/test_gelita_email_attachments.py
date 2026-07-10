"""Tests for Gelita email xlsx attachment filename rules and classification."""

from __future__ import annotations

import pytest

from app.domain.gelita.email_attachments import (
    classify_gelita_email_xlsx_attachments,
    is_load_tendering_attachment,
)


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("customers_orders_week12.xlsx", True),
        ("Customers_Orders_week12.xlsx", True),
        ("path/to/customers_orders_foo.xlsx", True),
        ("customers_orders_.xlsx", True),
        ("Customer_Orders.xlsx", False),
        ("Customer orders (1).xlsx", False),
        ("loads.xlsx", False),
        ("delivery_location.xlsx", False),
        ("customers_orders_week12.pdf", False),
        ("", False),
        (None, False),
    ],
)
def test_is_load_tendering_attachment(file_name: str | None, expected: bool) -> None:
    assert is_load_tendering_attachment(file_name) is expected


def test_classify_finds_both_attachments_in_one_pass() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "2", "extension": "xlsx", "name": "customers_orders_week.xlsx"},
        ],
    }

    classified = classify_gelita_email_xlsx_attachments(payload)

    assert classified.delivery_locations_attachment is not None
    assert classified.delivery_locations_attachment["id"] == "1"
    assert classified.load_tendering_xlsx_attachment is not None
    assert classified.load_tendering_xlsx_attachment["id"] == "2"


def test_classify_returns_empty_when_has_attachments_false() -> None:
    payload = {
        "has_attachments": False,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
        ],
    }

    classified = classify_gelita_email_xlsx_attachments(payload)

    assert classified.delivery_locations_attachment is None
    assert classified.load_tendering_xlsx_attachment is None


def test_classify_picks_first_match_per_type() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [
            {"id": "dl-1", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "dl-2", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "tender-1", "extension": "xlsx", "name": "customers_orders_a.xlsx"},
            {"id": "tender-2", "extension": "xlsx", "name": "customers_orders_b.xlsx"},
        ],
    }

    classified = classify_gelita_email_xlsx_attachments(payload)

    assert classified.delivery_locations_attachment["id"] == "dl-1"
    assert classified.load_tendering_xlsx_attachment["id"] == "tender-1"


def test_classify_picks_load_tendering_prefix_only() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "2", "extension": "xlsx", "name": "loads.xlsx"},
            {"id": "3", "extension": "xlsx", "name": "customers_orders_ship.xlsx"},
        ],
    }

    classified = classify_gelita_email_xlsx_attachments(payload)

    assert classified.load_tendering_xlsx_attachment is not None
    assert classified.load_tendering_xlsx_attachment["id"] == "3"


def test_classify_returns_none_load_tendering_without_prefix_match() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [
            {"id": "1", "extension": "xlsx", "name": "delivery_location.xlsx"},
            {"id": "2", "extension": "xlsx", "name": "Customer_Orders.xlsx"},
        ],
    }

    classified = classify_gelita_email_xlsx_attachments(payload)

    assert classified.delivery_locations_attachment is not None
    assert classified.load_tendering_xlsx_attachment is None
