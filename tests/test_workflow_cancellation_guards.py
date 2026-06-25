"""Pure workflow cancellation guard tests."""

from __future__ import annotations

from app.configs.workflow_cancellation_policies import DRIVER_ASSIGNMENT_CANCEL_POLICY
from app.domain.workflow_cancellation_guards import (
    is_workflow_cancelled,
    is_workflow_cancellable,
    is_workflow_success_terminal,
    workflow_ingress_terminal_sub_statuses,
)
from app.models.status import StatusSubType, StatusType


def test_is_workflow_cancelled() -> None:
    assert is_workflow_cancelled(StatusType.COMPLETED, StatusSubType.CANCELLED)
    assert not is_workflow_cancelled(StatusType.PENDING_REVIEW, StatusSubType.CANCELLED)


def test_is_workflow_cancellable_pending_review_reminder() -> None:
    assert is_workflow_cancellable(
        StatusType.PENDING_REVIEW,
        StatusSubType.REMINDER_1_SENT,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    )


def test_is_workflow_cancellable_rejects_success_terminal() -> None:
    assert not is_workflow_cancellable(
        StatusType.PENDING_REVIEW,
        StatusSubType.DETAILS_RECEIVED,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    )


def test_is_workflow_cancellable_rejects_already_cancelled() -> None:
    assert not is_workflow_cancellable(
        StatusType.COMPLETED,
        StatusSubType.CANCELLED,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    )


def test_workflow_ingress_terminal_includes_cancelled() -> None:
    terminals = workflow_ingress_terminal_sub_statuses(DRIVER_ASSIGNMENT_CANCEL_POLICY)
    assert StatusSubType.CANCELLED in terminals
    assert StatusSubType.DETAILS_RECEIVED in terminals


def test_is_workflow_success_terminal() -> None:
    assert is_workflow_success_terminal(
        StatusSubType.UPLOADED_TO_TMS,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    )
    assert not is_workflow_success_terminal(
        StatusSubType.REMINDER_1_SENT,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    )
