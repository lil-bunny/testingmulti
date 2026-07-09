"""Tests for shared TMS connection timeout activity logging."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.activity_log_constants import TMS_CONNECTION_TIMED_OUT_EXCEPTION
from app.models.activity_type import ActorType
from app.services.tms_connection_activity_service import TmsConnectionActivityService

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "22222222-3333-4444-5555-666666666666"


def test_record_timeout_calls_record_exception() -> None:
    activity = MagicMock()
    activity.record_exception.return_value = "log-1"
    svc = TmsConnectionActivityService(activity_log_service=activity)

    out = svc.record_timeout(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        workflow_run_id=_RUN_UUID,
        communication_id="comm-1",
    )

    assert out == "log-1"
    activity.record_exception.assert_called_once()
    write = activity.record_exception.call_args[0][0]
    assert write.tenant_id == _TENANT_UUID
    assert write.workflow_lifecycle_id == _LIFECYCLE_UUID
    assert write.workflow_run_id == _RUN_UUID
    assert write.description == TMS_CONNECTION_TIMED_OUT_EXCEPTION
    assert write.metadata is None
    assert write.communication_id == "comm-1"
    assert write.actor_type == ActorType.SYSTEM


def test_record_timeout_skips_missing_scope() -> None:
    activity = MagicMock()
    svc = TmsConnectionActivityService(activity_log_service=activity)
    assert svc.record_timeout(tenant_id="", workflow_lifecycle_id=_LIFECYCLE_UUID) is None
    activity.record_exception.assert_not_called()
