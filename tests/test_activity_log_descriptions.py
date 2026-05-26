"""Tests for activity log description helpers."""

from app.domain.activity_log_descriptions import (
    format_status_updated_to_processing,
    format_tender_created_action,
)


def test_format_tender_created_action() -> None:
    text = format_tender_created_action(
        tender_id="uuid-1",
        order_number="ORD-99",
        customer_name="Gelita NA",
    )
    assert text == "Tender ORD-99 created for Gelita NA"


def test_format_status_updated_to_processing() -> None:
    assert format_status_updated_to_processing() == "Status updated to Processing"
