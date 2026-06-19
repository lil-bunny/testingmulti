"""Tests for ``read_tender_row`` hydration and event-gated validation."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.domain.error_catalog import BusinessError
from app.domain.state import WorkflowState
from app.workflows.nodes.tenders import read_tender_row
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _state(*, event_type: str = "reminder_due") -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "tender_id": "tender-1",
            "workflow_lifecycle_id": "wl-1",
            "event_type": event_type,
            "tenant_settings": load_tenant_settings_dev("gelita"),
        },
    )


@patch("app.workflows.nodes.tenders.WorkflowLifecycleService")
@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_missing_delivery_date_on_reminder(
    mock_tender_cls, mock_lifecycle_cls
) -> None:
    mock_tender_cls.return_value.read_order.return_value = {
        "tender": {
            "order_number": "ORD-1",
            "load_type": "LTL",
            "delivery_date": None,
            "metadata": {},
        },
        "products": [],
    }

    result = read_tender_row(_state(event_type="reminder_due"))

    assert isinstance(result, dict)
    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_DELIVERY_DATE.value
    mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.assert_not_called()


@patch("app.workflows.nodes.tenders.WorkflowLifecycleService")
@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_allows_missing_delivery_date_on_tender_created(
    mock_tender_cls, mock_lifecycle_cls
) -> None:
    mock_tender_cls.return_value.read_order.return_value = {
        "tender": {
            "order_number": "ORD-1",
            "load_type": "LTL",
            "delivery_date": None,
            "delivery_address": {"country": "U.S.A.", "city": "Chicago", "state": "IL"},
            "metadata": {},
        },
        "products": [{"product_name": "A", "order_quantity": 1}],
    }
    mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
    }

    state = _state(event_type="tender_created")
    read_tender_row(state)

    assert state.data["tender"]["delivery_address"]["country"] == "U.S.A."
    assert state.data["is_domestic_delivery"] is True
    assert "error" not in state.data


@patch("app.workflows.nodes.tenders.WorkflowLifecycleService")
@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_marks_international_on_tender_created(
    mock_tender_cls, mock_lifecycle_cls
) -> None:
    mock_tender_cls.return_value.read_order.return_value = {
        "tender": {
            "order_number": "96820",
            "load_type": "LTL",
            "delivery_date": date(2026, 6, 20),
            "delivery_address": {"country": "Germany", "city": "SINSHEIM"},
            "metadata": {},
        },
        "products": [{"product_name": "A", "order_quantity": 1}],
    }
    mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
    }

    state = _state(event_type="tender_created")
    read_tender_row(state)

    assert state.data["is_domestic_delivery"] is False


@patch("app.workflows.nodes.tenders.TenderService")
def test_read_tender_row_tender_not_found_hard_fails_on_tender_created(
    mock_tender_cls,
) -> None:
    mock_tender_cls.return_value.read_order.return_value = None

    result = read_tender_row(_state(event_type="tender_created"))

    assert isinstance(result, dict)
    assert result["data"]["error"]["code"] == BusinessError.TENDER_NOT_FOUND.value


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

    state = _state(event_type="reminder_due")
    read_tender_row(state)

    assert state.data["tender"]["delivery_date"] == "2026-06-20"
