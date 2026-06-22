"""Tests for automatic-reply guard before carrier ack LLM classification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.workflows.graph.routers import automatic_reply_ack_router
from app.workflows.nodes.record_ack_received import guard_automatic_reply_ack
from tests.fixtures.outlook_auto_reply_emails import (
    EMAIL_ID_OOO_CHRIS,
    ack_received_ooo_webhook_payload,
)

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMM_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
THREAD_ID = "sample-thread-outlook-ooo-001"


def _state(**data_extra):
    data = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "tender_id": TENDER_UUID,
        "thread_id": THREAD_ID,
        "communication_id": COMM_UUID,
        "body": "We accept the load.",
        "type": "OUTLOOK",
        "subject": "RE: PICK UP REQUEST # 97061",
    }
    data.update(data_extra)
    return SimpleNamespace(tenant_id=TENANT_UUID, execution_id=RUN_UUID, data=data)


@pytest.mark.parametrize(
    ("flag", "expected_route"),
    [
        (True, "skipped"),
        (False, "continue"),
    ],
)
def test_automatic_reply_ack_router(flag: bool, expected_route: str) -> None:
    state = _state()
    if flag:
        state.data["automatic_reply_skipped"] = True
    assert automatic_reply_ack_router(state) == expected_route


@patch("app.workflows.nodes.record_ack_received.ActivityLogService")
def test_guard_automatic_reply_ack_records_exception(mock_svc_cls: MagicMock) -> None:
    mock_svc = mock_svc_cls.return_value
    payload = ack_received_ooo_webhook_payload(
        thread_id=THREAD_ID,
        lifecycle_id=LIFECYCLE_UUID,
        tender_id=TENDER_UUID,
        communication_id=COMM_UUID,
    )
    state = _state(**payload)

    out = guard_automatic_reply_ack(state)

    assert out.data["automatic_reply_skipped"] is True
    mock_svc.record_exception.assert_called_once()
    write = mock_svc.record_exception.call_args.args[0]
    assert write.workflow_run_id == RUN_UUID
    assert write.workflow_lifecycle_id == LIFECYCLE_UUID
    assert write.communication_id == COMM_UUID
    assert "Auto-reply skipped" in (write.description or "")
    assert write.metadata["reason"] == "automatic_reply"
    assert write.metadata["email_id"] == EMAIL_ID_OOO_CHRIS


@patch("app.workflows.nodes.record_ack_received.ActivityLogService")
def test_guard_automatic_reply_ack_passes_real_reply(mock_svc_cls: MagicMock) -> None:
    state = _state()

    out = guard_automatic_reply_ack(state)

    assert "automatic_reply_skipped" not in out.data
    mock_svc_cls.return_value.record_exception.assert_not_called()


@patch("app.workflows.nodes.record_ack_received.ActivityLogService")
def test_guard_automatic_reply_ack_gmail_same_subject_not_skipped(
    mock_svc_cls: MagicMock,
) -> None:
    state = _state(
        type="GMAIL",
        subject="Automatic reply: PICK UP REQUEST # 97061",
    )

    guard_automatic_reply_ack(state)

    mock_svc_cls.return_value.record_exception.assert_not_called()


@patch("app.workflows.nodes.record_ack_received.ActivityLogService")
def test_guard_automatic_reply_ack_webhook_without_type(mock_svc_cls: MagicMock) -> None:
    state = _state(
        subject="Automatic reply: Fw: PICK UP REQUEST # 97088 PO# 169-00",
        body="I am out of the office. Contact someone else",
        email_id="BNzSNEkkV1qOOEVL_uZfHg",
    )
    state.data.pop("type", None)

    guard_automatic_reply_ack(state)

    assert state.data["automatic_reply_skipped"] is True
    mock_svc_cls.return_value.record_exception.assert_called_once()


@patch("app.workflows.nodes.record_ack_received.ActivityLogService")
def test_guard_automatic_reply_ack_routes_to_end(mock_svc_cls: MagicMock) -> None:
    payload = ack_received_ooo_webhook_payload()
    state = _state(**payload)
    guard_automatic_reply_ack(state)

    assert automatic_reply_ack_router(state) == "skipped"
    mock_svc_cls.return_value.record_exception.assert_called_once()
