"""Tests for WorkflowException / @safe_node error handling in appointment scheduling nodes."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.domain.state import WorkflowState
from app.services.appointment_scheduling.ascend_write_service import AscendWriteResult
from app.services.appointment_scheduling.email_service import ConfirmationEmailResult
from app.services.appointment_scheduling.email_service import AppointmentSchedulingSendResult
from app.services.appointment_scheduling.intake_service import IntakeResult
from app.services.appointment_scheduling.turvo_stop_update_service import TurvoConfirmResult
from app.services.appointment_scheduling.turvo_stop_update_service import TurvoWriteResult
from app.services.appointment_scheduling.weekend_pickup_service import WeekendPickupResult
from app.workflows.nodes.appointment_scheduling.nodes import (
    apply_ascend_dropoff_appointment,
    apply_turvo_delivery_appointment,
    apply_turvo_delivery_placeholder,
    apply_turvo_tender_status,
    apply_weekend_shifted_pickup,
    run_scheduling_intake,
    send_appointment_confirmation_reply,
    send_appointment_scheduling_email,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
LIFECYCLE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
        data={
            "shipment_id": "SHP-001",
            "load_id": "LD-001",
            "workflow_lifecycle_id": LIFECYCLE_ID,
            **data,
        },
    )


def _assert_error(result, expected_code, expected_category: str) -> None:
    assert isinstance(result, dict), "safe_node should return dict on error"
    error = result["data"]["error"]
    assert error["code"] == expected_code.value
    assert error["category"] == expected_category
    assert error["message"]


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingIntakeService")
@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingLifecycleService")
def test_run_scheduling_intake_business_failure_uses_global_sink(
    mock_lifecycle_cls,
    mock_intake_cls,
) -> None:
    failure = SchedulingFailure.from_catalog(
        BusinessError.MISSING_RECIPIENT_EMAIL,
        "Recipient email is missing for customer Acme.",
    )
    mock_intake_cls.return_value.run_intake.return_value = IntakeResult(
        ok=False,
        failure=failure,
    )

    result = run_scheduling_intake(_state())

    _assert_error(result, BusinessError.MISSING_RECIPIENT_EMAIL, BusinessError.CATEGORY.value)
    mock_lifecycle_cls.return_value.mark_failed.assert_not_called()


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingIntakeService")
def test_run_scheduling_intake_integration_failure(mock_intake_cls) -> None:
    failure = SchedulingFailure.from_catalog(
        IntegrationError.ASCEND_LOGIN_FAILED,
        "Ascend login failed (HTTP 401).",
    )
    mock_intake_cls.return_value.run_intake.return_value = IntakeResult(
        ok=False,
        failure=failure,
    )

    result = run_scheduling_intake(_state())

    _assert_error(result, IntegrationError.ASCEND_LOGIN_FAILED, IntegrationError.CATEGORY.value)


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingEmailService")
def test_send_appointment_scheduling_email_missing_mikey_is_business(mock_email_cls) -> None:
    mock_email_cls.return_value.send_draft_from_state.return_value = AppointmentSchedulingSendResult(
        sent=False,
        error="missing_mikey_account_id",
    )

    result = send_appointment_scheduling_email(_state())

    _assert_error(result, BusinessError.MISSING_MIKEY_ACCOUNT_ID, BusinessError.CATEGORY.value)


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingEmailService")
def test_send_appointment_scheduling_email_unipile_is_integration(mock_email_cls) -> None:
    mock_email_cls.return_value.send_draft_from_state.return_value = AppointmentSchedulingSendResult(
        sent=False,
        error="Unipile timeout",
    )

    result = send_appointment_scheduling_email(_state())

    _assert_error(result, IntegrationError.EMAIL_SEND_FAILED, IntegrationError.CATEGORY.value)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoStopUpdateService"
)
def test_apply_turvo_delivery_placeholder_missing_stop_is_business(
    mock_confirm_cls,
) -> None:
    failure = SchedulingFailure.from_wire(
        "missing_delivery_stop_or_date",
        "missing delivery stop or date",
    )
    mock_confirm_cls.return_value.apply_delivery_placeholder_from_state.return_value = (
        TurvoConfirmResult(ok=False, error="missing_delivery_stop_or_date", failure=failure)
    )

    result = apply_turvo_delivery_placeholder(_state())

    _assert_error(result, BusinessError.MISSING_DELIVERY_STOP_OR_DATE, BusinessError.CATEGORY.value)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoStopUpdateService"
)
def test_apply_turvo_delivery_missing_fields_is_business(
    mock_turvo_cls,
) -> None:
    failure = SchedulingFailure.from_wire(
        "missing_turvo_update_fields",
        "missing turvo update fields",
    )
    mock_turvo_cls.return_value.apply_delivery_from_state.return_value = TurvoWriteResult(
        ok=False,
        error="missing_turvo_update_fields",
        failure=failure,
    )

    result = apply_turvo_delivery_appointment(_state())

    _assert_error(result, BusinessError.MISSING_TURVO_UPDATE_FIELDS, BusinessError.CATEGORY.value)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoStopUpdateService"
)
def test_apply_turvo_delivery_api_error_is_integration(
    mock_turvo_cls,
) -> None:
    failure = SchedulingFailure.from_catalog(
        IntegrationError.TURVO_STOP_UPDATE_FAILED,
        "Turvo HTTP 500",
    )
    mock_turvo_cls.return_value.apply_delivery_from_state.return_value = TurvoWriteResult(
        ok=False,
        error="turvo_stop_update_failed",
        failure=failure,
    )

    result = apply_turvo_delivery_appointment(_state())

    _assert_error(result, IntegrationError.TURVO_STOP_UPDATE_FAILED, IntegrationError.CATEGORY.value)


@patch("app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingEmailService")
def test_send_confirmation_reply_failure_hard_fails(
    mock_confirm_cls,
) -> None:
    mock_confirm_cls.return_value.send_confirmation_reply_from_state.return_value = ConfirmationEmailResult(
        sent=False,
        error="missing_mikey_account_id",
    )

    result = send_appointment_confirmation_reply(_state())

    _assert_error(result, BusinessError.MISSING_MIKEY_ACCOUNT_ID, BusinessError.CATEGORY.value)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoStopUpdateService"
)
def test_apply_turvo_tender_status_failure_sets_tender_integration_error(
    mock_turvo_cls,
) -> None:
    failure = SchedulingFailure.from_catalog(
        IntegrationError.TURVO_TENDER_STATUS_FAILED,
        "Turvo tender PUT failed",
    )
    mock_turvo_cls.return_value.tender_from_state.return_value = TurvoWriteResult(
        ok=False,
        error="turvo_tender_status_failed",
        failure=failure,
    )

    result = apply_turvo_tender_status(_state(confirmation_sent=True))

    _assert_error(result, IntegrationError.TURVO_TENDER_STATUS_FAILED, IntegrationError.CATEGORY.value)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTurvoStopUpdateService"
)
def test_apply_turvo_tender_status_skips_when_confirmation_not_sent(
    mock_turvo_cls,
) -> None:
    state = _state(confirmation_sent=False)

    result = apply_turvo_tender_status(state)

    assert result is state
    assert "error" not in state.data
    mock_turvo_cls.return_value.tender_from_state.assert_not_called()


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingWeekendPickupService"
)
def test_apply_weekend_shifted_pickup_preserves_business_category(
    mock_weekend_cls,
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


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingWeekendPickupService"
)
def test_apply_weekend_shifted_pickup_skip_does_not_set_error(
    mock_weekend_cls,
) -> None:
    mock_weekend_cls.return_value.apply_from_state.return_value = WeekendPickupResult(
        ok=True,
        skipped=True,
    )

    state = _state()
    result = apply_weekend_shifted_pickup(state)

    assert result is state
    assert "error" not in state.data


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingAscendWriteService"
)
def test_apply_ascend_dropoff_preserves_integration_category(
    mock_ascend_cls,
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


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingAscendWriteService"
)
def test_apply_ascend_dropoff_skip_does_not_set_error(
    mock_ascend_cls,
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


def test_scheduling_failure_from_wire_known_business() -> None:
    failure = SchedulingFailure.from_wire(
        "missing_mikey_account_id",
        "missing mikey account id",
    )

    assert failure.code == BusinessError.MISSING_MIKEY_ACCOUNT_ID.value
    assert failure.category == BusinessError.CATEGORY


def test_scheduling_failure_from_wire_unknown_is_system() -> None:
    failure = SchedulingFailure.from_wire("totally_unknown_wire", "boom")

    assert failure.code == "totally_unknown_wire"
    assert failure.category == SystemError.CATEGORY


def test_scheduling_failure_to_workflow_exception_preserves_catalog_category() -> None:
    failure = SchedulingFailure.from_catalog(
        BusinessError.ASCEND_NOT_CONFIGURED,
        "Ascend credentials are not configured.",
    )

    exc = failure.to_workflow_exception()

    assert exc.error_code == BusinessError.ASCEND_NOT_CONFIGURED.value
    assert exc.error_category == BusinessError.CATEGORY
    assert exc.message == "Ascend credentials are not configured."
