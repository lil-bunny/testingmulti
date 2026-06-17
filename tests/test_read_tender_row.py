"""Tests for ``read_tender_row`` delivery date validation."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.domain.error_catalog import BusinessError
from app.domain.state import WorkflowState
from app.workflows.nodes.tenders import read_tender_row


def _state() -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "tender_id": "tender-1",
            "workflow_lifecycle_id": "wl-1",
        },
    )


@patch("app.workflows.nodes.tenders.WorkflowLifecycleService")
@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_missing_delivery_date(mock_tender_cls, mock_lifecycle_cls) -> None:
    mock_tender_cls.return_value.read_order.return_value = {
        "tender": {
            "order_number": "ORD-1",
            "load_type": "LTL",
            "delivery_date": None,
            "metadata": {},
        },
        "products": [],
    }

    result = read_tender_row(_state())

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_DELIVERY_DATE.value
    mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.assert_not_called()


@patch("app.workflows.nodes.tenders.WorkflowLifecycleService")
@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_plumbs_delivery_date(mock_tender_cls, mock_lifecycle_cls) -> None:
    mock_tender_cls.return_value.read_order.return_value = {
        "tender": {
            "order_number": "ORD-1",
            "load_type": "LTL",
            "delivery_date": date(2026, 6, 20),
            "metadata": {},
        },
        "products": [],
    }
    mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
    }

    state = _state()
    read_tender_row(state)

    assert state.data["tender"]["delivery_date"] == "2026-06-20"
