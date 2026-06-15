"""Tests for WorkflowErrorAlertService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, workflow_error_payload
from app.domain.workflow_error_alert_payload import WorkflowErrorAlertPayload
from app.services.workflow_error_alert_service import WorkflowErrorAlertService


TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _payload() -> WorkflowErrorAlertPayload:
    return WorkflowErrorAlertPayload(
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
        error=workflow_error_payload(
            code=BusinessError.MISSING_PACK_CODE.value,
            message=BusinessError.MISSING_PACK_CODE.description,
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
    activity_log_service.record_action.assert_called_once()
    write = activity_log_service.record_action.call_args.args[0]
    assert write.description == BusinessError.MISSING_PACK_CODE.description


@patch("app.services.workflow_error_alert_service.send_email")
def test_send_workflow_error_alert_missing_delivery_address(
    mock_send_email: MagicMock,
) -> None:
    mock_send_email.return_value = {
        "success": True,
        "communication_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    }
    communications_service = MagicMock()
    communications_service.find_outbound_id_by_idempotency_key.return_value = None
    activity_log_service = MagicMock()

    payload = WorkflowErrorAlertPayload(
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
        error=workflow_error_payload(
            code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
            message=BusinessError.MISSING_DELIVERY_ADDRESS.description,
            category=BusinessError.CATEGORY,
        ),
        tenant_settings={
            **_payload().tenant_settings,
            "load_tendering": {
                **_payload().tenant_settings["load_tendering"],
                "workflow_error_alerts": {
                    "enabled": True,
                    "channels": [
                        {
                            "channel": "email",
                            "to": ["ops@example.com"],
                            "cc": [],
                            "bcc": [],
                            "subject": "Exception PO {customer_po}",
                            "body_template": (
                                "<p>{failure_reason}</p>"
                                "{delivery_location_code_block}"
                                "<p>{order_number}</p>"
                            ),
                        }
                    ],
                },
            },
        },
        delivery_address_code="41000100",
        workflow_data={
            "tender": {"order_number": "ORD-9", "customer_po": "PO-9"},
            "delivery_address_code": "41000100",
        },
    )

    service = WorkflowErrorAlertService(
        communications_service=communications_service,
        activity_log_service=activity_log_service,
    )
    service.send_workflow_error_alert(payload)

    mock_send_email.assert_called_once()
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["subject"] == "Exception PO PO-9"
    assert BusinessError.MISSING_DELIVERY_ADDRESS.description in kwargs["body"]
    assert "Delivery Location Code" in kwargs["body"]
    assert "41000100" in kwargs["body"]
    assert "ORD-9" in kwargs["body"]
    metadata = kwargs["communication_metadata"]
    assert metadata["error_code"] == BusinessError.MISSING_DELIVERY_ADDRESS.value
    assert metadata["delivery_address_code"] == "41000100"
    write = activity_log_service.record_action.call_args.args[0]
    assert write.description == BusinessError.MISSING_DELIVERY_ADDRESS.description


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
    activity_log_service.record_action.assert_not_called()
