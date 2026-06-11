"""Tests for Gelita load-tender email attachment filename rules."""

from __future__ import annotations

import pytest

from app.domain.load_tendering_import import (
    email_load_tender_xlsx_attachment,
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


def test_email_load_tender_xlsx_attachment_picks_prefixed_file() -> None:
    payload = {
        "attachments": [
            {"id": "1", "name": "delivery_location.xlsx", "extension": "xlsx"},
            {"id": "2", "name": "loads.xlsx", "extension": "xlsx"},
            {"id": "3", "name": "customers_orders_ship.xlsx", "extension": "xlsx"},
        ],
    }
    att = email_load_tender_xlsx_attachment(payload)
    assert att is not None
    assert att["id"] == "3"


def test_email_load_tender_xlsx_attachment_returns_none_without_prefix_match() -> None:
    payload = {
        "attachments": [
            {"id": "1", "name": "delivery_location.xlsx", "extension": "xlsx"},
            {"id": "2", "name": "Customer_Orders.xlsx", "extension": "xlsx"},
        ],
    }
    assert email_load_tender_xlsx_attachment(payload) is None
