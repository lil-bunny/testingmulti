"""DriverAssignmentIngressService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.driver_assignment_ingress_service import DriverAssignmentIngressService

_TENANT_ID = "tenant-uuid-1"
_SHIPMENTS_ROW_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_RATECON_LC_ID = "ratecon-lc-1"
_DRIVER_LC_ID = "driver-lc-1"
_PICKUP_AT = "2026-03-30T15:30:00+00:00"


def _patch_run_workflow_async(**apply_async_kwargs):
    """Patch lazy import target without loading Celery task module."""
    apply_async = MagicMock(**apply_async_kwargs)
    mock_module = MagicMock()
    mock_module.run_workflow_async.apply_async = apply_async
    return patch.dict("sys.modules", {"app.tasks.workflows": mock_module}), apply_async


def _turvo_shipment_fixture() -> dict:
    return {
        "details": {
            "transportation": {"mode": {"key": "24105", "value": "TL"}},
            "status": {"code": {"key": "2102", "value": "Covered"}},
            "globalRoute": [
                {
                    "deleted": False,
                    "stopType": {"value": "pickup"},
                    "appointment": {
                        "date": _PICKUP_AT,
                        "timeZone": "America/Los_Angeles",
                    },
                }
            ],
            "carrierOrder": [],
        }
    }


def _enabled_settings() -> dict:
    return {"enabledProcesses": ["driver_assignment"]}


def _disabled_settings() -> dict:
    return {"enabledProcesses": ["pod_lifecycle"]}


def _ratecon_success_state_data(**overrides) -> dict:
    data = {
        "tenant_id": _TENANT_ID,
        "tenant_slug": "t3ra",
        "tenant_settings": _enabled_settings(),
        "shipments_row_id": _SHIPMENTS_ROW_ID,
        "shipment_id": "1000324895",
        "load_id": "load-1",
        "workflow_lifecycle_id": _RATECON_LC_ID,
        "thread_id": "thread-1",
        "shipment": _turvo_shipment_fixture(),
        "ratecon_s3_upload": {
            "all_succeeded": True,
            "results": [{"document_persist": {"stored": True}}],
        },
        "document_analysis_ratecon": {"stored": True},
    }
    data.update(overrides)
    return data


def _base_payload(**overrides) -> dict:
    payload = {
        "event_type": WorkflowRunEventType.RATECON_COMPLETED.value,
        "tenant_id": _TENANT_ID,
        "tenant_slug": "t3ra",
        "tenant_settings": _enabled_settings(),
        "shipments_row_id": _SHIPMENTS_ROW_ID,
        "shipment_id": "1000324895",
        "load_id": "load-1",
        "thread_id": "thread-1",
        "ratecon_workflow_lifecycle_id": _RATECON_LC_ID,
        "pickup_appointment_at": _PICKUP_AT,
        "pickup_appointment_timezone": "America/Los_Angeles",
        "pickup_appointment_source": "globalRoute.appointment.date",
        "shipment": _turvo_shipment_fixture(),
    }
    payload.update(overrides)
    return payload


def _service(**gate_overrides) -> DriverAssignmentIngressService:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.DOCUMENT_PROCESSED.value,
    }
    lifecycle.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _DRIVER_LC_ID,
    }

    runs = MagicMock()
    runs.is_workflow_initial_path_blocked.return_value = gate_overrides.get(
        "duplicate", False
    )

    shipments = MagicMock()
    shipments.get_by_id.return_value = {"id": _SHIPMENTS_ROW_ID}

    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"

    activity = MagicMock()

    return DriverAssignmentIngressService(
        lifecycle_service=lifecycle,
        runs_service=runs,
        shipments_service=shipments,
        communications_service=comms,
        activity_service=activity,
    )


def test_try_enqueue_skips_when_ratecon_analysis_not_stored():
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        data=_ratecon_success_state_data(document_analysis_ratecon={"stored": False}),
    )
    with _patch_run_workflow_async()[0]:
        result = DriverAssignmentIngressService().try_enqueue_from_ratecon_state(state)

    assert result.enqueued is False
    assert result.skip_reason == "ratecon_analysis_not_stored"


def test_try_enqueue_happy_path_queues_once():
    svc = _service(duplicate=False)
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]
    state = SimpleNamespace(tenant_id=_TENANT_ID, data=_ratecon_success_state_data())
    celery_task = MagicMock(id="celery-1")

    patch_ctx, apply_async = _patch_run_workflow_async(return_value=celery_task)
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is True
    assert result.execution_id
    assert result.celery_task_id == "celery-1"
    apply_async.assert_called_once()
    kwargs = apply_async.call_args.kwargs["kwargs"]
    assert kwargs["workflow_name"] == "driver_assignment"
    assert kwargs["payload"]["event_type"] == WorkflowRunEventType.RATECON_COMPLETED.value
    assert kwargs["payload"]["ratecon_workflow_lifecycle_id"] == _RATECON_LC_ID
    assert kwargs["payload"]["pickup_appointment_at"] == _PICKUP_AT


def test_try_enqueue_skips_missing_pickup_and_logs_ratecon_activity():
    svc = _service()
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        execution_id="ratecon-run-1",
        data=_ratecon_success_state_data(
            shipment={
                "details": {
                    "transportation": {"mode": {"key": "24105", "value": "TL"}},
                    "status": {"code": {"key": "2102", "value": "Covered"}},
                    "globalRoute": [],
                    "carrierOrder": [],
                }
            }
        ),
    )

    patch_ctx, apply_async = _patch_run_workflow_async()
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is False
    assert result.skip_reason == "pickup_appointment_not_found"
    apply_async.assert_not_called()
    svc._activity.record_not_started_on_ratecon.assert_called_once()


def test_try_enqueue_skips_wrong_mode_and_logs_ratecon_activity():
    svc = _service()
    shipment = _turvo_shipment_fixture()
    shipment["details"]["transportation"] = {"mode": {"key": "24104", "value": "LTL"}}
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        execution_id="ratecon-run-1",
        data=_ratecon_success_state_data(shipment=shipment),
    )

    patch_ctx, apply_async = _patch_run_workflow_async()
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is False
    assert result.skip_reason == "transportation_mode_not_tl"
    apply_async.assert_not_called()
    svc._activity.record_not_started_on_ratecon.assert_called_once()


def test_try_enqueue_skips_not_covered_and_logs_ratecon_activity():
    svc = _service()
    shipment = _turvo_shipment_fixture()
    shipment["details"]["status"] = {"code": {"key": "2101", "value": "Tendered"}}
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        execution_id="ratecon-run-1",
        data=_ratecon_success_state_data(shipment=shipment),
    )

    patch_ctx, apply_async = _patch_run_workflow_async()
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is False
    assert result.skip_reason == "shipment_not_covered"
    apply_async.assert_not_called()
    svc._activity.record_not_started_on_ratecon.assert_called_once()


def test_try_enqueue_skips_excluded_carrier_and_logs_ratecon_activity():
    svc = _service()
    shipment = _turvo_shipment_fixture()
    shipment["details"]["carrierOrder"] = [
        {"deleted": False, "carrier": {"name": "Convoy Platform"}},
    ]
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        execution_id="ratecon-run-1",
        data=_ratecon_success_state_data(shipment=shipment),
    )

    patch_ctx, apply_async = _patch_run_workflow_async()
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is False
    assert result.skip_reason == "excluded_carrier"
    apply_async.assert_not_called()
    svc._activity.record_not_started_on_ratecon.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_skips_when_shipment_not_covered():
    svc = _service(duplicate=False)
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]
    shipment = _turvo_shipment_fixture()
    shipment["details"]["status"] = {"code": {"key": "2116", "value": "Route complete"}}

    result = await svc.prepare_ratecon_completed_payload(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        payload=_base_payload(shipment=shipment),
    )

    assert result.skipped is True
    assert result.skip_reason == "shipment_not_covered"


@pytest.mark.asyncio
async def test_prepare_raises_without_pickup_appointment_at():
    svc = _service()
    payload = _base_payload()
    payload.pop("pickup_appointment_at")
    payload["shipment"] = {
        "details": {
            "transportation": {"mode": {"key": "24105", "value": "TL"}},
            "status": {"code": {"key": "2102", "value": "Covered"}},
            "globalRoute": [],
            "carrierOrder": [],
        }
    }

    with pytest.raises(Exception, match="Missing pickup_appointment_at"):
        await svc.prepare_ratecon_completed_payload(
            tenant_id=_TENANT_ID,
            tenant_slug="t3ra",
            payload=payload,
        )


@pytest.mark.asyncio
async def test_prepare_skips_on_duplicate_ratecon_completed():
    svc = _service(duplicate=True)
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]

    result = await svc.prepare_ratecon_completed_payload(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        payload=_base_payload(),
    )

    assert result.skipped is True
    assert result.skip_reason == "duplicate_ratecon_completed"


@pytest.mark.asyncio
async def test_prepare_skips_when_process_disabled():
    svc = _service(duplicate=False)
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]

    result = await svc.prepare_ratecon_completed_payload(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        payload=_base_payload(tenant_settings=_disabled_settings()),
    )

    assert result.skipped is True
    assert result.skip_reason == "process_disabled"


@pytest.mark.asyncio
async def test_prepare_raises_when_load_id_missing():
    svc = _service()
    payload = _base_payload()
    payload.pop("load_id")

    with pytest.raises(Exception, match="Missing required payload keys"):
        await svc.prepare_ratecon_completed_payload(
            tenant_id=_TENANT_ID,
            tenant_slug="t3ra",
            payload=payload,
        )


def test_check_reminder_eligibility_ok_when_ratecon_duplicate_would_block():
    svc = _service(duplicate=True)
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(event_type="reminder_due"),
    )

    assert result.eligible is True
    svc._runs_service.is_workflow_initial_path_blocked.assert_not_called()


def test_check_reminder_eligibility_skips_when_driver_assigned():
    svc = _service()
    svc._driver_lifecycle_terminal = MagicMock(return_value=False)  # type: ignore[method-assign]
    shipment = _turvo_shipment_fixture()
    shipment["details"]["carrierOrder"] = [
        {
            "deleted": False,
            "drivers": [
                {
                    "deleted": False,
                    "phone": {"number": "5551234567"},
                }
            ],
        }
    ]

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(event_type="reminder_due", shipment=shipment),
    )

    assert result.skip_reason == "driver_already_assigned"


def test_send_reminder_email_success():
    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-uuid-1",
    }
    svc = DriverAssignmentIngressService(communications_service=comms)

    result = svc.send_reminder_email(
        tenant_id=_TENANT_ID,
        tenant_settings={"mikey_account_id": "acct-1"},
        payload=_base_payload(
            event_type="reminder_due",
            reminder_step=1,
            body="Please send driver info",
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    assert result.error is None
    assert result.communication_id == "comm-uuid-1"
    comms.send_thread_reply.assert_called_once()
    call_kwargs = comms.send_thread_reply.call_args.kwargs
    assert call_kwargs["thread_id"] == "thread-1"
    assert call_kwargs["body"] == "Please send driver info"
