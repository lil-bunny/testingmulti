"""Tests for activity log description helpers."""

from app.domain.activity_log_descriptions import (
    format_tender_created_action,
    generate_activity_log_description,
)
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType


def test_format_tender_created_action() -> None:
    text = format_tender_created_action(
        tender_id="uuid-1",
        order_number="ORD-99",
        customer_name="Gelita NA",
    )
    assert text == "Tender ORD-99 created for Gelita NA"


def test_generate_status_change_description() -> None:
    text = generate_activity_log_description(
        activity_type=ActivityType.STATUS_CHANGE,
        from_status=StatusType.NONE,
        to_status=StatusType.PROCESSING,
        from_sub_status=StatusSubType.NONE,
        to_sub_status=StatusSubType.TENDER_CREATED,
    )
    assert text == "Status changed from None to Processing"


def test_generate_status_change_ignores_sub_status() -> None:
    text = generate_activity_log_description(
        activity_type=ActivityType.STATUS_CHANGE,
        from_status=StatusType.PROCESSING,
        to_status=StatusType.COMPLETED,
        from_sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
        to_sub_status=StatusSubType.ACCEPTED,
    )
    assert text == "Status changed from Processing to Completed"


def test_generate_sub_status_change_description() -> None:
    text = generate_activity_log_description(
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        from_status=StatusType.PENDING_REVIEW,
        to_status=StatusType.PENDING_REVIEW,
        from_sub_status=StatusSubType.TENDER_SENT_TO_TENANT,
        to_sub_status=StatusSubType.ESCALATED,
    )
    assert text == "Sub-status changed from Tender Sent To Shipper to Escalated"


def test_generate_action_returns_none() -> None:
    assert (
        generate_activity_log_description(
            activity_type=ActivityType.ACTION,
            from_status=StatusType.NONE,
            to_status=StatusType.NONE,
            from_sub_status=StatusSubType.NONE,
            to_sub_status=StatusSubType.NONE,
        )
        is None
    )
