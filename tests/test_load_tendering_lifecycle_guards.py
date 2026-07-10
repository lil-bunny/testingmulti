"""Tests for execution-time load_tendering lifecycle guards."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason


def test_delayed_step_skips_completed() -> None:
    assert (
        delayed_workflow_step_skip_reason(
            {"status": StatusType.COMPLETED.value, "sub_status": "accepted"},
        )
        == "lifecycle_already_completed"
    )


def test_delayed_step_skips_accepted_sub_status() -> None:
    assert (
        delayed_workflow_step_skip_reason(
            {
                "status": StatusType.PENDING_REVIEW.value,
                "sub_status": StatusSubType.ACCEPTED.value,
            },
        )
        == "terminal_sub_status_accepted"
    )


def test_delayed_step_skips_escalated_sub_status() -> None:
    assert (
        delayed_workflow_step_skip_reason(
            {
                "status": StatusType.PENDING_REVIEW.value,
                "sub_status": StatusSubType.ESCALATED.value,
            },
        )
        == "terminal_sub_status_escalated"
    )


def test_delayed_step_skips_configured_sub_status() -> None:
    assert (
        delayed_workflow_step_skip_reason(
            {
                "status": StatusType.PENDING_REVIEW.value,
                "sub_status": "reminder_1_sent",
            },
            skip_sub_statuses=frozenset({"escalated", "reminder_1_sent"}),
        )
        == "skip_sub_status_reminder_1_sent"
    )


def test_delayed_step_allows_tender_sent_to_carrier() -> None:
    assert (
        delayed_workflow_step_skip_reason(
            {
                "status": StatusType.PENDING_REVIEW.value,
                "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
            },
            skip_sub_statuses=frozenset({"escalated"}),
        )
        is None
    )
