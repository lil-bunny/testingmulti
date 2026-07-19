"""Tests for WorkflowErrorAlertService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, format_error_message, workflow_error_payload
from app.domain.workflow_error_alert_payload import WorkflowErrorAlertPayload
from app.services.workflow_error_alert_service import WorkflowErrorAlertService


TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
EXCEPTION_ACTIVITY_LOG_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


PACK_MSG = format_error_message(BusinessError.MISSING_PACK_CODE, pack_code="5366")


def _payload() -> WorkflowErrorAlertPayload:
    return WorkflowErrorAlertPayload(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        workflow_name="load_tendering",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
        error=workflow_error_payload(
            code=BusinessError.MISSING_PACK_CODE.value,
            message=PACK_MSG,
            category=BusinessError.CATEGORY,
        ),
        tenant_settings={
            "ana_at_gelita_account_id": "acct-1",
            "load_tendering": {
                "workflow_error_alerts": {
                    "enabled": True,
                    "channels": [
                        {
                            "channel": "email",
                            "to": ["ana.gelita.test@freightx.ai"],
                            "cc": ["cc@example.com"],
                            "bcc": [],
                            "subject": "Exception PO {customer_po}",
                            "body_template": "<p>{failure_reason}</p><p>{order_number}</p>",
                        }
                    ],
                }
            },
        },
        workflow_data={
            "tender": {"order_number": "ORD-9", "customer_po": "PO-9"},
        },
        exception_activity_log_id=EXCEPTION_ACTIVITY_LOG_UUID,
    )


@patch("app.services.workflow_error_alert_service.send_email")
def test_send_workflow_error_alert_email_channel(mock_send_email: MagicMock) -> None:
    mock_send_email.return_value = {
        "success": True,
        "communication_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    }
    communications_service = MagicMock()
    communications_service.find_outbound_id_by_idempotency_key.return_value = None
    activity_log_service = MagicMock()

    service = WorkflowErrorAlertService(
        communications_service=communications_service,
        activity_log_service=activity_log_service,
    )
    service.send_workflow_error_alert(_payload())

    mock_send_email.assert_called_once()
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["to"] == ["ana.gelita.test@freightx.ai"]
    assert kwargs["cc"] == ["cc@example.com"]
    assert kwargs["account_id"] == "acct-1"
    assert kwargs["subject"] == "Exception PO PO-9"
    assert "pack code" in kwargs["body"].lower() or "required" in kwargs["body"].lower()
    metadata = kwargs["communication_metadata"]
    assert metadata["error_code"] == BusinessError.MISSING_PACK_CODE.value
    assert metadata["idempotency_key"]
    activity_log_service.link_communication.assert_called_once()
    link_kwargs = activity_log_service.link_communication.call_args.kwargs
    assert link_kwargs["activity_log_id"] == EXCEPTION_ACTIVITY_LOG_UUID
    assert link_kwargs["communication_id"] == "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    assert link_kwargs["metadata_patch"]["channel"] == "email"
    assert link_kwargs["metadata_patch"]["alert_type"] == "workflow_error_alert"


@patch("app.services.workflow_error_alert_service.send_email")
def test_send_skips_duplicate_idempotency(mock_send_email: MagicMock) -> None:
    communications_service = MagicMock()
    communications_service.find_outbound_id_by_idempotency_key.return_value = (
        "existing-comm-id"
    )
    activity_log_service = MagicMock()

    service = WorkflowErrorAlertService(
        communications_service=communications_service,
        activity_log_service=activity_log_service,
    )
    service.send_workflow_error_alert(_payload())

    mock_send_email.assert_not_called()
    activity_log_service.link_communication.assert_called_once_with(
        activity_log_id=EXCEPTION_ACTIVITY_LOG_UUID,
        tenant_id=TENANT_UUID,
        communication_id="existing-comm-id",
        metadata_patch={
            "channel": "email",
            "alert_type": "workflow_error_alert",
        },
    )
