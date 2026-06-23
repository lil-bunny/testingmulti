"""Driver assignment lifecycle guard unit tests."""

from __future__ import annotations

from app.domain.driver_assignment_lifecycle_guards import (
    blocks_driver_assignment_escalation,
    blocks_driver_assignment_reminder,
    is_driver_assignment_active,
    is_driver_assignment_cancelled,
    is_driver_assignment_success_terminal,
)
from app.models.status import StatusSubType, StatusType


def test_is_driver_assignment_cancelled() -> None:
    assert is_driver_assignment_cancelled(StatusType.COMPLETED, StatusSubType.CANCELLED)
    assert not is_driver_assignment_cancelled(StatusType.PROCESSING, StatusSubType.CANCELLED)
    assert not is_driver_assignment_cancelled(StatusType.COMPLETED, StatusSubType.UPLOADED_TO_TMS)


def test_is_driver_assignment_active() -> None:
    assert is_driver_assignment_active(StatusType.PROCESSING, StatusSubType.REMINDER_1_SENT)
    assert not is_driver_assignment_active(StatusType.COMPLETED, StatusSubType.CANCELLED)


def test_is_driver_assignment_success_terminal() -> None:
    assert is_driver_assignment_success_terminal(
        StatusType.PROCESSING, StatusSubType.DETAILS_RECEIVED
    )
    assert not is_driver_assignment_success_terminal(
        StatusType.COMPLETED, StatusSubType.CANCELLED
    )


def test_blocks_driver_assignment_reminder_matrix() -> None:
    assert blocks_driver_assignment_reminder(
        {"status": StatusType.COMPLETED.value, "sub_status": StatusSubType.CANCELLED.value}
    )
    assert blocks_driver_assignment_reminder(
        {
            "status": StatusType.PROCESSING.value,
            "sub_status": StatusSubType.DETAILS_RECEIVED.value,
        }
    )
    assert not blocks_driver_assignment_reminder(
        {
            "status": StatusType.PROCESSING.value,
            "sub_status": StatusSubType.REMINDER_1_SENT.value,
        }
    )
    assert not blocks_driver_assignment_reminder(
        {
            "status": StatusType.PENDING_REVIEW.value,
            "sub_status": StatusSubType.REMINDER_2_SENT.value,
        }
    )
    assert blocks_driver_assignment_reminder(
        {
            "status": StatusType.PENDING_REVIEW.value,
            "sub_status": StatusSubType.REMINDER_4_SENT.value,
        }
    )
    assert blocks_driver_assignment_reminder(
        {
            "status": StatusType.PENDING_REVIEW.value,
            "sub_status": StatusSubType.DETAILS_RECEIVED.value,
        }
    )


def test_blocks_driver_assignment_escalation_matrix() -> None:
    assert blocks_driver_assignment_escalation(
        {"status": StatusType.PROCESSING.value, "sub_status": StatusSubType.ESCALATED.value}
    )
    assert blocks_driver_assignment_escalation(
        {
            "status": StatusType.PROCESSING.value,
            "sub_status": StatusSubType.UPLOADED_TO_TMS.value,
        }
    )
    assert not blocks_driver_assignment_escalation(
        {
            "status": StatusType.PROCESSING.value,
            "sub_status": StatusSubType.REMINDER_4_SENT.value,
        }
    )
