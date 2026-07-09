"""Tests for DriverAssignmentActivityService TMS timeout EXCEPTION path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.activity_log_constants import TMS_CONNECTION_TIMED_OUT_EXCEPTION
from app.models.activity_type import ActivityType
from app.services.driver_assignment.activity_service import DriverAssignmentActivityService

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "22222222-3333-4444-5555-666666666666"


def _state(*, tms_connection_timed_out: bool = False, tms_driver_error: str = "tms_shipment_fetch_failed"):
    return SimpleNamespace(
        tenant_id=_TENANT_UUID,
        execution_id=_RUN_UUID,
        data={
            "workflow_lifecycle_id": _LIFECYCLE_UUID,
            "tenant_id": _TENANT_UUID,
            "tms_connection_timed_out": tms_connection_timed_out,
            "tms_driver_error": tms_driver_error,
        },
    )


def test_record_tms_driver_error_timeout_writes_exception() -> None:
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)

    with patch(
        "app.services.driver_assignment.activity_service.TmsConnectionActivityService.record_timeout",
        return_value="log-1",
    ) as record_timeout:
        svc.record_tms_driver_error(_state(tms_connection_timed_out=True))

    record_timeout.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        workflow_run_id=_RUN_UUID,
        communication_id=None,
    )
    activity.record_sequence.assert_not_called()


def test_record_tms_driver_error_non_timeout_writes_action() -> None:
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)

    with patch(
        "app.services.driver_assignment.activity_service.TmsConnectionActivityService.record_timeout",
    ) as record_timeout:
        svc.record_tms_driver_error(_state(tms_connection_timed_out=False))

    record_timeout.assert_not_called()
    activity.record_sequence.assert_called_once()
    seq = activity.record_sequence.call_args[0][0]
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert TMS_CONNECTION_TIMED_OUT_EXCEPTION not in (seq.steps[0].description or "")
