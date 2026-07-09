"""Tests for Gelita ``escalate_tender`` reminder cancel + lifecycle update."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.models.status import StatusSubType, StatusType
from app.workflows.nodes.escalate_tender import escalate_tender
from tests.fixtures.tenant_settings import load_tenant_settings_dev

LIFECYCLE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _state() -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="gelita",
        execution_id=RUN_ID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_ID,
            "tender_id": TENDER_ID,
            "tenant_settings": load_tenant_settings_dev("gelita"),
            "tender": {"load_type": "ftl", "order_number": "97001"},
        },
    )


@patch("app.workflows.nodes.escalate_tender.ActivityLogService")
@patch("app.workflows.nodes.escalate_tender.send_email")
@patch("app.workflows.nodes.escalate_tender.WorkflowReminderCancelService")
@patch("app.workflows.nodes.escalate_tender.WorkflowLifecycleService")
def test_escalate_tender_cancels_reminders_then_updates_lifecycle(
    mock_lifecycle_cls: MagicMock,
    mock_cancel_cls: MagicMock,
    mock_send_email: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER_3.value,
    }
    mock_cancel = MagicMock()
    mock_cancel_cls.return_value = mock_cancel
    mock_send_email.return_value = {"success": True, "communication_id": "comm-1"}
    mock_activity = MagicMock()
    mock_activity_cls.return_value = mock_activity

    state = _state()
    result = escalate_tender(state)

    assert result is state
    assert result.data.get("escalation_email_sent") is True
    assert result.data.get("escalation_sub_status") == StatusSubType.ESCALATED.value
    mock_cancel.cancel_all.assert_called_once_with(lifecycle_id=LIFECYCLE_ID)
    mock_send_email.assert_called_once()
    mock_activity.record_sequence.assert_called_once()


@patch("app.workflows.nodes.escalate_tender.ActivityLogService")
@patch("app.workflows.nodes.escalate_tender.send_email")
@patch("app.workflows.nodes.escalate_tender.WorkflowReminderCancelService")
@patch("app.workflows.nodes.escalate_tender.WorkflowLifecycleService")
def test_escalate_tender_already_escalated_cancels_reminders_and_skips_send(
    mock_lifecycle_cls: MagicMock,
    mock_cancel_cls: MagicMock,
    mock_send_email: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.ESCALATED.value,
    }
    mock_cancel = MagicMock()
    mock_cancel_cls.return_value = mock_cancel

    state = _state()
    result = escalate_tender(state)

    assert result is state
    assert result.data.get("escalation_skipped") == "terminal_sub_status_escalated"
    assert result.data.get("escalation_email_sent") is False
    mock_cancel.cancel_all.assert_called_once_with(lifecycle_id=LIFECYCLE_ID)
    mock_send_email.assert_not_called()
    mock_activity_cls.return_value.record_sequence.assert_not_called()


@patch("app.workflows.nodes.escalate_tender.ActivityLogService")
@patch("app.workflows.nodes.escalate_tender.TenderService")
@patch("app.workflows.nodes.escalate_tender.send_email")
@patch("app.workflows.nodes.escalate_tender.WorkflowReminderCancelService")
@patch("app.workflows.nodes.escalate_tender.WorkflowLifecycleService")
def test_escalate_tender_loads_order_number_when_missing_from_state(
    mock_lifecycle_cls: MagicMock,
    mock_cancel_cls: MagicMock,
    mock_send_email: MagicMock,
    mock_tender_cls: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    """Reject→exhausted never hits read_tender_row; resolve order from tender_id."""
    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER_3.value,
    }
    mock_cancel_cls.return_value = MagicMock()
    mock_send_email.return_value = {"success": True, "communication_id": "comm-1"}
    mock_activity_cls.return_value = MagicMock()
    mock_tender = MagicMock()
    mock_tender_cls.return_value = mock_tender
    mock_tender.read_order.return_value = {
        "tender": {"order_number": "97001", "load_type": "FTL"},
        "products": [],
    }

    state = _state()
    state.data["tender"] = {"load_type": "ftl"}  # no order_number (ack reject path)
    result = escalate_tender(state)

    assert result is state
    assert result.data.get("order_number") == "97001"
    mock_tender.read_order.assert_called_once_with(
        tenant_id=TENANT_ID,
        tender_id=TENDER_ID,
    )
    subject = mock_send_email.call_args.kwargs["subject"]
    body = mock_send_email.call_args.kwargs["body"]
    assert "97001" in subject
    assert "97001" in body
    assert "unknown" not in subject
    assert "unknown" not in body
