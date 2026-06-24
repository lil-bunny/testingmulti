"""WorkflowLifecycleCancelOrchestrator unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.workflow_cancel_trigger import (
    RATECON_SUPERSEDED_TRIGGER,
    SHIPMENT_TENDERED_TRIGGER,
    WorkflowCancelTrigger,
)
from app.services.driver_assignment.cancel_service import WorkflowCancelAdapterResult
from app.services.workflow_lifecycle_cancel_orchestrator import (
    WorkflowLifecycleCancelOrchestrator,
)
from app.services.workflow_lifecycle_cancel_service import WorkflowCancelResult

_TENANT_ID = "tenant-uuid-1"


def _trigger(**overrides) -> WorkflowCancelTrigger:
    base = {
        "trigger": SHIPMENT_TENDERED_TRIGGER,
        "tenant_id": _TENANT_ID,
        "tenant_slug": "t3ra",
        "shipment_number": "1000324895",
        "load_id": "30389",
        "metadata": {"vendor": "turvo"},
    }
    base.update(overrides)
    return WorkflowCancelTrigger(**base)


def test_orchestrator_returns_driver_assignment_result() -> None:
    mock_da = MagicMock()
    mock_da.cancel_for_trigger.return_value = WorkflowCancelAdapterResult(
        cancelled=True,
        lifecycle_id="lc-1",
        skip_reason=None,
    )
    with patch.dict(
        "app.services.workflow_lifecycle_cancel_orchestrator._CANCEL_ADAPTERS",
        {"driver_assignment": mock_da},
    ):
        results = WorkflowLifecycleCancelOrchestrator().cancel_for_trigger(_trigger())

    assert results["driver_assignment"].cancelled is True
    assert results["driver_assignment"].lifecycle_id == "lc-1"
    content = WorkflowLifecycleCancelOrchestrator.to_api_content(results)
    assert content["cancelled"] is True
    assert content["lifecycle_id"] == "lc-1"
    assert "workflows" in content
    assert content["workflows"]["driver_assignment"]["cancelled"] is True


def test_orchestrator_ratecon_superseded_fans_out() -> None:
    mock_ratecon = MagicMock()
    mock_ratecon.cancel_for_trigger.return_value = WorkflowCancelAdapterResult(
        cancelled=True,
        lifecycle_id="ratecon-lc-old",
    )
    mock_da = MagicMock()
    mock_da.cancel_for_trigger.return_value = WorkflowCancelAdapterResult(
        cancelled=True,
        lifecycle_id="da-lc-1",
    )
    with patch.dict(
        "app.services.workflow_lifecycle_cancel_orchestrator._CANCEL_ADAPTERS",
        {
            "ratecon": mock_ratecon,
            "driver_assignment": mock_da,
        },
    ):
        results = WorkflowLifecycleCancelOrchestrator().cancel_for_trigger(
            _trigger(
                trigger=RATECON_SUPERSEDED_TRIGGER,
                shipments_row_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            )
        )

    assert results["ratecon"].cancelled is True
    assert results["ratecon"].lifecycle_id == "ratecon-lc-old"
    assert results["driver_assignment"].cancelled is True
    assert results["driver_assignment"].lifecycle_id == "da-lc-1"
    mock_ratecon.cancel_for_trigger.assert_called_once()
    mock_da.cancel_for_trigger.assert_called_once()


def test_orchestrator_unknown_trigger_returns_empty() -> None:
    results = WorkflowLifecycleCancelOrchestrator().cancel_for_trigger(
        _trigger(trigger="unknown_trigger")
    )
    assert results == {}


def test_orchestrator_api_content_backward_compat_on_skip() -> None:
    results = {
        "driver_assignment": WorkflowCancelResult(
            cancelled=False,
            skip_reason="no_active_lifecycle",
        )
    }
    content = WorkflowLifecycleCancelOrchestrator.to_api_content(results)
    assert content["cancelled"] is False
    assert content["skip_reason"] == "no_active_lifecycle"
