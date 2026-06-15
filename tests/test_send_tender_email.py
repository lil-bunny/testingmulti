"""Tests for Gelita ``send_tender_email`` address validation."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.error_catalog import BusinessError
from app.domain.state import WorkflowState
from app.workflows.nodes.send_tender_email import send_tender_email
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _state(*, tender: dict) -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "workflow_lifecycle_id": "lifecycle-1",
            "tender_id": "tender-1",
            "tenant_settings": load_tenant_settings_dev("gelita"),
            "tender": {
                "load_type": "ltl",
                "pickup_address": "GELITA USA\n123 Main St\nSIOUX CITY IA 51101",
                "delivery_address": "ACME\n456 Oak Ave\nCHICAGO IL 60601",
                "tender_products": [{"product_name": "Widget", "pack_code": "5366"}],
                **tender,
            },
        },
    )


@patch("app.workflows.nodes.send_tender_email.send_email")
def test_send_tender_email_missing_delivery_address(mock_send_email) -> None:
    mock_send_email.return_value = {"success": True, "communication_id": "comm-1"}
    state = _state(tender={"delivery_address": ""})

    result = send_tender_email(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_DELIVERY_ADDRESS.value
    assert error["category"] == BusinessError.CATEGORY.value
    mock_send_email.assert_not_called()


@patch("app.workflows.nodes.send_tender_email.send_email")
def test_send_tender_email_missing_pickup_address(mock_send_email) -> None:
    mock_send_email.return_value = {"success": True, "communication_id": "comm-1"}
    state = _state(tender={"pickup_address": None})

    result = send_tender_email(state)

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_PICKUP_ADDRESS.value
    assert error["category"] == BusinessError.CATEGORY.value
    mock_send_email.assert_not_called()
