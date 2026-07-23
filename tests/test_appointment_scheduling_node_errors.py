"""Tests for WorkflowException / @safe_node error handling in appointment scheduling nodes."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.error_catalog import BusinessError, IntegrationError
from app.domain.state import WorkflowState
from app.services.appointment_scheduling.ascend_write_service import AscendWriteResult
from app.services.appointment_scheduling.turvo_write_service import TurvoWriteResult
from app.services.appointment_scheduling.weekend_pickup_service import WeekendPickupResult
from app.workflows.nodes.appointment_scheduling.nodes import (
    apply_ascend_dropoff_appointment,
    apply_turvo_tender_status,
    apply_weekend_shifted_pickup,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
        data={"shipment_id": "SHP-001", "load_id": "LD-001", **data},
    )


def _assert_error(result, expected_code, expected_category: str) -> None:
    assert isinstance(result, dict), "safe_node should return dict on error"
    error = result["data"]["error"]
    assert error["code"] == expected_code.value
    assert error["category"] == expected_category
    assert error["message"]


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingActivityService")
@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoWriteService"
)
def test_apply_turvo_tender_status_failure_sets_integration_error(
    mock_turvo_cls,
    mock_activity_cls,
) -> None:
    mock_turvo_cls.return_value.tender_from_state.return_value = TurvoWriteResult(
        ok=False,
        error="Turvo tender PUT failed",
    )

    result = apply_turvo_tender_status(_state(confirmation_sent=True))

    _assert_error(result, IntegrationError.VENDOR_API_ERROR, IntegrationError.CATEGORY.value)
    mock_activity_cls.return_value.record_turvo_tendered.assert_not_called()


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoWriteService"
)
def test_apply_turvo_tender_status_skips_when_confirmation_not_sent(
    mock_turvo_cls,
) -> None:
    state = _state(confirmation_sent=False)

    result = apply_turvo_tender_status(state)

    assert result is state
    assert "error" not in state.data
    mock_turvo_cls.return_value.tender_from_state.assert_not_called()


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingActivityService")
@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingWeekendPickupService"
)
def test_apply_weekend_shifted_pickup_preserves_business_category(
    mock_weekend_cls,
    mock_activity_cls,
) -> None:
    failure = SchedulingFailure.from_catalog(
        BusinessError.ASCEND_NOT_CONFIGURED,
        "Ascend credentials are not configured.",
    )
    mock_weekend_cls.return_value.apply_from_state.return_value = WeekendPickupResult(
        ok=False,
        failure=failure,
    )

    result = apply_weekend_shifted_pickup(_state())

    _assert_error(result, BusinessError.ASCEND_NOT_CONFIGURED, BusinessError.CATEGORY.value)
    mock_activity_cls.return_value.record_weekend_pickup_update.assert_called_once()


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingActivityService")
@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingWeekendPickupService"
)
def test_apply_weekend_shifted_pickup_skip_does_not_set_error(
    mock_weekend_cls,
    mock_activity_cls,
) -> None:
    mock_weekend_cls.return_value.apply_from_state.return_value = WeekendPickupResult(
        ok=True,
        skipped=True,
    )

    state = _state()
    result = apply_weekend_shifted_pickup(state)

    assert result is state
    assert "error" not in state.data
    mock_activity_cls.return_value.record_weekend_pickup_update.assert_called_once()


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingActivityService")
@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingAscendWriteService"
)
def test_apply_ascend_dropoff_preserves_integration_category(
    mock_ascend_cls,
    mock_activity_cls,
) -> None:
    failure = SchedulingFailure.from_catalog(
        IntegrationError.ASCEND_DROPOFF_UPDATE_FAILED,
        "Ascend dropoff appointment update failed for REF-1.",
    )
    mock_ascend_cls.return_value.apply_dropoff_from_state.return_value = AscendWriteResult(
        ok=False,
        failure=failure,
    )

    result = apply_ascend_dropoff_appointment(_state())

    _assert_error(
        result,
        IntegrationError.ASCEND_DROPOFF_UPDATE_FAILED,
        IntegrationError.CATEGORY.value,
    )
    mock_activity_cls.return_value.record_ascend_update.assert_called_once()


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingActivityService")
@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingAscendWriteService"
)
def test_apply_ascend_dropoff_skip_does_not_set_error(
    mock_ascend_cls,
    mock_activity_cls,
) -> None:
    mock_ascend_cls.return_value.apply_dropoff_from_state.return_value = AscendWriteResult(
        ok=True,
        skipped=True,
        dry_run=True,
    )

    state = _state()
    result = apply_ascend_dropoff_appointment(state)

    assert result is state
    assert "error" not in state.data
    mock_activity_cls.return_value.record_ascend_update.assert_called_once()


def test_scheduling_failure_to_workflow_exception_preserves_catalog_category() -> None:
    failure = SchedulingFailure.from_catalog(
        BusinessError.ASCEND_NOT_CONFIGURED,
        "Ascend credentials are not configured.",
    )

    exc = failure.to_workflow_exception()

    assert exc.error_code == BusinessError.ASCEND_NOT_CONFIGURED.value
    assert exc.error_category == BusinessError.CATEGORY
    assert exc.message == "Ascend credentials are not configured."
