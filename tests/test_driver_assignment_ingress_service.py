"""DriverAssignmentIngressService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.ingress_result import IngressResult
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from app.services.workflow_shadow_mail_service import WorkflowShadowMailService

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
    runs.is_ratecon_completed_blocked_for_shipment.return_value = gate_overrides.get(
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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
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


def test_try_enqueue_enqueues_when_turvo_driver_assigned() -> None:
    svc = _service(duplicate=False)
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
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
    state = SimpleNamespace(
        tenant_id=_TENANT_ID,
        data=_ratecon_success_state_data(shipment=shipment),
    )
    celery_task = MagicMock(id="celery-2")

    patch_ctx, apply_async = _patch_run_workflow_async(return_value=celery_task)
    with patch_ctx:
        result = svc.try_enqueue_from_ratecon_state(state)

    assert result.enqueued is True
    apply_async.assert_called_once()


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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]

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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]

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
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(event_type="reminder_due"),
    )

    assert result.eligible is True


def test_check_reminder_eligibility_skips_when_lifecycle_cancelled():
    svc = _service()
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.CANCELLED.value,
    }

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(
            event_type="reminder_due",
            workflow_lifecycle_id=_DRIVER_LC_ID,
        ),
    )

    assert result.skip_reason == "already_completed"


def test_check_reminder_eligibility_skips_when_driver_assigned():
    svc = _service()
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
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


def test_send_reminder_email_passes_from_email_when_alias_configured():
    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-uuid-1",
    }
    svc = DriverAssignmentIngressService(communications_service=comms)

    result = svc.send_reminder_email(
        tenant_id=_TENANT_ID,
        tenant_settings={
            "mikey_account_id": {
                "account_id": "acct-1",
                "email_alias": "ops@example.com",
            }
        },
        payload=_base_payload(
            event_type="reminder_due",
            reminder_step=1,
            body="Please send driver info",
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    call_kwargs = comms.send_thread_reply.call_args.kwargs
    assert call_kwargs["account_id"] == "acct-1"
    assert call_kwargs["from_email"] == "ops@example.com"


def test_send_reminder_email_shadow_blocks_without_redirect():
    comms = MagicMock()
    svc = DriverAssignmentIngressService(communications_service=comms)
    settings = {
        "mikey_account_id": "acct-1",
        "driver_assignment": {"shadow_mode": True},
    }

    result = svc.send_reminder_email(
        tenant_id=_TENANT_ID,
        tenant_settings=settings,
        payload=_base_payload(
            event_type="reminder_due",
            reminder_step=1,
            body="Please send driver info",
            thread_id="thread-1",
            workflow_shadow_mode=True,
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    assert result.error is None
    assert result.communication_id is None
    comms.send_thread_reply.assert_not_called()


def test_send_reminder_email_shadow_redirects_without_thread_reply():
    comms = MagicMock()
    svc = DriverAssignmentIngressService(communications_service=comms)
    settings = {
        "mikey_account_id": "acct-1",
        "driver_assignment": {
            "shadow_mode": True,
            "shadow_emails": {"to": ["test@freightx.ai"]},
        },
    }

    with patch.object(
        WorkflowShadowMailService,
        "send_redirect_email",
        return_value={"success": True, "communication_id": "comm-shadow-1"},
    ) as redirect_mock:
        result = svc.send_reminder_email(
            tenant_id=_TENANT_ID,
            tenant_settings=settings,
            payload=_base_payload(
                event_type="reminder_due",
                reminder_step=1,
                body="Please send driver info",
                thread_id="thread-1",
                workflow_shadow_mode=True,
            ),
            workflow_run_id="run-1",
        )

    assert result.sent is True
    assert result.communication_id == "comm-shadow-1"
    comms.send_thread_reply.assert_not_called()
    redirect_mock.assert_called_once()
    call_kwargs = redirect_mock.call_args.kwargs
    assert call_kwargs["recipients"].to == ["test@freightx.ai"]
    assert call_kwargs["communication_metadata"]["original_thread_id"] == "thread-1"


def test_send_reminder_email_shadow_redirect_without_thread_id():
    comms = MagicMock()
    svc = DriverAssignmentIngressService(communications_service=comms)
    settings = {
        "mikey_account_id": "acct-1",
        "driver_assignment": {
            "shadow_mode": True,
            "shadow_emails": {"to": ["test@freightx.ai"]},
        },
    }

    with patch.object(
        WorkflowShadowMailService,
        "send_redirect_email",
        return_value={"success": True, "communication_id": "comm-shadow-2"},
    ) as redirect_mock:
        result = svc.send_reminder_email(
            tenant_id=_TENANT_ID,
            tenant_settings=settings,
            payload=_base_payload(
                event_type="reminder_due",
                reminder_step=1,
                body="Please send driver info",
                thread_id=None,
                ratecon_workflow_lifecycle_id=None,
                workflow_shadow_mode=True,
            ),
            workflow_run_id="run-1",
        )

    assert result.sent is True
    assert result.communication_id == "comm-shadow-2"
    comms.send_thread_reply.assert_not_called()
    comms.resolve_thread_for_lifecycle.assert_not_called()
    redirect_mock.assert_called_once()


def test_send_partial_details_follow_up_email_bumps_reminder_step():
    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-partial-1",
    }
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    svc = DriverAssignmentIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    result = svc.send_partial_details_follow_up_email(
        tenant_id=_TENANT_ID,
        tenant_settings={"mikey_account_id": "acct-1"},
        payload=_base_payload(
            event_type="driver_details_email_received",
            workflow_lifecycle_id=_DRIVER_LC_ID,
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    assert result.reminder_step == 2
    meta = comms.send_thread_reply.call_args.kwargs["communication_metadata"]
    assert meta["source"] == "driver_details_partial_follow_up"
    assert "complete driver details" in comms.send_thread_reply.call_args.kwargs["body"]


def test_send_partial_details_follow_up_uses_tenant_template():
    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-partial-custom",
    }
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    svc = DriverAssignmentIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    result = svc.send_partial_details_follow_up_email(
        tenant_id=_TENANT_ID,
        tenant_settings={
            "mikey_account_id": "acct-1",
            "driver_assignment": {
                "partial_follow_up_email": {
                    "template_html": "<p>Please send name and phone for load</p>",
                }
            },
        },
        payload=_base_payload(
            event_type="driver_details_email_received",
            workflow_lifecycle_id=_DRIVER_LC_ID,
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    call_kwargs = comms.send_thread_reply.call_args.kwargs
    assert call_kwargs["body"] == "<p>Please send name and phone for load</p>"


def test_send_partial_follow_up_at_reminder_4_still_sends():
    comms = MagicMock()
    comms.resolve_thread_for_lifecycle.return_value = "thread-1"
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-partial-cap",
    }
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_4_SENT.value,
    }
    svc = DriverAssignmentIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    result = svc.send_partial_details_follow_up_email(
        tenant_id=_TENANT_ID,
        tenant_settings={"mikey_account_id": "acct-1"},
        payload=_base_payload(
            event_type="driver_details_email_received",
            workflow_lifecycle_id=_DRIVER_LC_ID,
        ),
        workflow_run_id="run-1",
    )

    assert result.sent is True
    assert result.skip_sub_status_bump is True
    assert result.reminder_step == 4
    call_kwargs = comms.send_thread_reply.call_args.kwargs
    assert call_kwargs["communication_metadata"]["source"] == "driver_details_partial_follow_up"
    assert call_kwargs["communication_metadata"]["reminder_step"] == 4
    assert "complete driver details" in call_kwargs["body"]


def test_check_reminder_eligibility_skips_when_step_already_sent():
    svc = _service()
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(event_type="reminder_due", reminder_step=2),
    )

    assert result.skip_reason == "reminder_step_already_sent"


def test_check_reminder_eligibility_allows_next_step_on_pending_review_ladder():
    svc = _service()
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }

    result = svc.check_reminder_eligibility(
        tenant_id=_TENANT_ID,
        payload=_base_payload(
            event_type="reminder_due",
            reminder_step=3,
            workflow_lifecycle_id=_DRIVER_LC_ID,
        ),
    )

    assert result.eligible is True


def test_try_driver_details_email_received_rejects_non_reply_without_re_subject():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    result = svc.try_driver_details_email_received(
        payload={"thread_id": "thread-1", "body": "Driver John"},
        tenant=tenant,
    )
    assert result is None


def test_try_driver_details_email_received_enqueues_with_object_in_reply_to():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    svc._communications.find_active_lifecycle_id_for_thread.return_value = _DRIVER_LC_ID
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc._lifecycle_service.read_correlation_by_id.return_value = {
        "shipment_id": _SHIPMENTS_ROW_ID,
    }
    svc._shipments.get_by_id.return_value = {
        "id": _SHIPMENTS_ROW_ID,
        "shipment_number": "1000324895",
        "metadata": {"load_id": "load-1"},
    }
    svc._lifecycle_service.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _RATECON_LC_ID,
    }

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    patch_ctx, apply_async = _patch_run_workflow_async(return_value=MagicMock(id="celery-2"))
    with (
        patch_ctx,
        patch(
            "app.services.driver_assignment.ingress_driver_details_inbound.TenantsService"
        ) as tenants,
    ):
        tenants.return_value.get_by_slug.return_value = {
            "settings": _enabled_settings(),
        }
        resp = svc.try_driver_details_email_received(
            payload={
                "thread_id": "thread-1",
                "in_reply_to": {
                    "message_id": "<parent@example.com>",
                    "id": "mail-parent-1",
                },
                "body": "Driver John 555-0100",
            },
            tenant=tenant,
            communication_id="comm-1",
        )

    assert resp is not None
    apply_async.assert_called_once()


def test_try_driver_details_email_received_re_subject_fallback_enqueues():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    svc._communications.find_active_lifecycle_id_for_thread.return_value = _DRIVER_LC_ID
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc._lifecycle_service.read_correlation_by_id.return_value = {
        "shipment_id": _SHIPMENTS_ROW_ID,
    }
    svc._shipments.get_by_id.return_value = {
        "id": _SHIPMENTS_ROW_ID,
        "shipment_number": "1000324895",
        "metadata": {"load_id": "load-1"},
    }
    svc._lifecycle_service.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _RATECON_LC_ID,
    }

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    patch_ctx, apply_async = _patch_run_workflow_async(return_value=MagicMock(id="celery-2"))
    with (
        patch_ctx,
        patch(
            "app.services.driver_assignment.ingress_driver_details_inbound.TenantsService"
        ) as tenants,
    ):
        tenants.return_value.get_by_slug.return_value = {
            "settings": _enabled_settings(),
        }
        resp = svc.try_driver_details_email_received(
            payload={
                "thread_id": "thread-1",
                "subject": "Re: Rate confirmation for shipment: #30389",
                "body": "Driver John 555-0100",
            },
            tenant=tenant,
            communication_id="comm-1",
        )

    assert resp is not None
    apply_async.assert_called_once()


def test_try_driver_details_email_received_resolves_lifecycle_via_shipment_on_thread():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    svc._communications.find_active_lifecycle_id_for_thread.return_value = None
    svc._communications.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": _RATECON_LC_ID,
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_ID,
            "shipment_number": "1000324895",
        }
    ]
    svc._lifecycle_service.find_active_driver_assignment_lifecycle_id.return_value = _DRIVER_LC_ID
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc._lifecycle_service.read_correlation_by_id.return_value = {
        "shipment_id": _SHIPMENTS_ROW_ID,
    }
    svc._shipments.get_by_id.return_value = {
        "id": _SHIPMENTS_ROW_ID,
        "shipment_number": "1000324895",
        "metadata": {"load_id": "load-1"},
    }

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    patch_ctx, apply_async = _patch_run_workflow_async(return_value=MagicMock(id="celery-2"))
    with (
        patch_ctx,
        patch(
            "app.services.driver_assignment.ingress_driver_details_inbound.TenantsService"
        ) as tenants,
    ):
        tenants.return_value.get_by_slug.return_value = {
            "settings": _enabled_settings(),
        }
        resp = svc.try_driver_details_email_received(
            payload={
                "thread_id": "thread-1",
                "in_reply_to": {
                    "message_id": "<parent@example.com>",
                    "id": "mail-parent-1",
                },
                "body": "Driver John 555-0100",
            },
            tenant=tenant,
            communication_id="comm-1",
        )

    assert resp is not None
    svc._communications.find_shipment_context_for_thread.assert_called_once()
    svc._lifecycle_service.find_active_driver_assignment_lifecycle_id.assert_called_once_with(
        tenant_id=_TENANT_ID,
        shipment_id=_SHIPMENTS_ROW_ID,
    )
    apply_async.assert_called_once()


def test_try_driver_details_email_received_shipment_fallback_no_driver_lifecycle():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    svc._communications.find_active_lifecycle_id_for_thread.return_value = None
    svc._communications.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": _RATECON_LC_ID,
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_ID,
            "shipment_number": "1000324895",
        }
    ]
    svc._lifecycle_service.find_active_driver_assignment_lifecycle_id.return_value = None

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    with patch(
        "app.services.driver_assignment.ingress_driver_details_inbound.TenantsService"
    ) as tenants:
        tenants.return_value.get_by_slug.return_value = {
            "settings": _enabled_settings(),
        }
        result = svc.try_driver_details_email_received(
            payload={
                "thread_id": "thread-1",
                "in_reply_to": "parent-msg",
            },
            tenant=tenant,
        )

    assert result is None


def test_try_driver_details_email_received_enqueues_when_active_lifecycle():
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    svc = _service()
    svc._communications.find_active_lifecycle_id_for_thread.return_value = _DRIVER_LC_ID
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc._lifecycle_service.read_correlation_by_id.return_value = {
        "shipment_id": _SHIPMENTS_ROW_ID,
    }
    svc._shipments.get_by_id.return_value = {
        "id": _SHIPMENTS_ROW_ID,
        "shipment_number": "1000324895",
        "metadata": {"load_id": "load-1"},
    }
    svc._lifecycle_service.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _RATECON_LC_ID,
    }

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_ID, tenant_slug="t3ra")
    patch_ctx, apply_async = _patch_run_workflow_async(return_value=MagicMock(id="celery-2"))
    with (
        patch_ctx,
        patch(
            "app.services.driver_assignment.ingress_driver_details_inbound.TenantsService"
        ) as tenants,
    ):
        tenants.return_value.get_by_slug.return_value = {
            "settings": _enabled_settings(),
        }
        resp = svc.try_driver_details_email_received(
            payload={
                "thread_id": "thread-1",
                "in_reply_to": "parent-msg",
                "body": "Driver John 555-0100",
            },
            tenant=tenant,
            communication_id="comm-1",
        )

    assert resp is not None
    assert isinstance(resp, IngressResult)
    assert resp.outcome == "enqueued"
    apply_async.assert_called_once()
    kwargs = apply_async.call_args.kwargs["kwargs"]
    assert kwargs["workflow_name"] == "driver_assignment"
    assert (
        kwargs["payload"]["event_type"]
        == WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value
    )
    assert kwargs["payload"]["ratecon_workflow_lifecycle_id"] == _RATECON_LC_ID


def test_blocks_restart_for_shipment_when_active_processing() -> None:
    lifecycle = MagicMock()
    lifecycle.find_active_driver_assignment_lifecycle_id.return_value = _DRIVER_LC_ID
    lifecycle.has_success_terminal_driver_assignment_lifecycle.return_value = False
    svc = DriverAssignmentIngressService(lifecycle_service=lifecycle)
    assert svc._blocks_restart_for_shipment(
        tenant_id=_TENANT_ID,
        shipments_row_id=_SHIPMENTS_ROW_ID,
    )


def test_blocks_restart_for_shipment_when_success_terminal() -> None:
    lifecycle = MagicMock()
    lifecycle.find_active_driver_assignment_lifecycle_id.return_value = None
    lifecycle.has_success_terminal_driver_assignment_lifecycle.return_value = True
    svc = DriverAssignmentIngressService(lifecycle_service=lifecycle)
    assert svc._blocks_restart_for_shipment(
        tenant_id=_TENANT_ID,
        shipments_row_id=_SHIPMENTS_ROW_ID,
    )


def test_blocks_restart_for_shipment_allows_after_cancel_only() -> None:
    lifecycle = MagicMock()
    lifecycle.find_active_driver_assignment_lifecycle_id.return_value = None
    lifecycle.has_success_terminal_driver_assignment_lifecycle.return_value = False
    svc = DriverAssignmentIngressService(lifecycle_service=lifecycle)
    assert not svc._blocks_restart_for_shipment(
        tenant_id=_TENANT_ID,
        shipments_row_id=_SHIPMENTS_ROW_ID,
    )


@pytest.mark.asyncio
async def test_prepare_allows_restart_after_cancelled_cycle() -> None:
    svc = _service(duplicate=False)
    svc._blocks_restart_for_shipment = MagicMock(return_value=False)  # type: ignore[method-assign]

    result = await svc.prepare_ratecon_completed_payload(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        payload=_base_payload(),
    )

    assert result.skipped is False
    svc._runs_service.is_ratecon_completed_blocked_for_shipment.assert_called_once()


def test_check_reminder_eligibility_skips_when_driver_assigned():
    svc = DriverAssignmentIngressService()
    result = svc.send_driver_details_confirmation_email(
        tenant_id=_TENANT_ID,
        tenant_settings={
            "driver_assignment": {
                "confirmation_email": {"turvo_app_template_html": "<p>{driver_name}</p>"},
            }
        },
        payload={
            "tms_resolution": "skipped_already_assigned",
            "tms_driver_outcome": "assigned",
            "workflow_lifecycle_id": _DRIVER_LC_ID,
            "thread_id": "thread-1",
        },
    )
    assert result.sent is False
    assert result.error == "skipped_already_assigned"


def test_send_driver_details_confirmation_picks_turvo_template() -> None:
    comms = MagicMock()
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-out-1",
    }
    svc = DriverAssignmentIngressService(communications_service=comms)
    settings = {
        "mikey_account_id": "acct-1",
        "driver_assignment": {
            "confirmation_email": {
                "fourkites_template_html": "<p>FK {driver_name}</p>",
                "turvo_app_template_html": "<p>Turvo {driver_name} {driver_phone}</p>",
            }
        },
    }
    result = svc.send_driver_details_confirmation_email(
        tenant_id=_TENANT_ID,
        tenant_settings=settings,
        payload={
            "tms_resolution": "found",
            "tms_driver_outcome": "assigned",
            "tms_is_tracking_customer": False,
            "workflow_lifecycle_id": _DRIVER_LC_ID,
            "thread_id": "thread-1",
            "driver_details_extraction": {
                "driver": {"name": "anna", "phone": "555-0100"},
            },
        },
        workflow_run_id="run-1",
    )
    assert result.sent is True
    body = comms.send_thread_reply.call_args.kwargs["body"]
    assert "Turvo anna" in body
    assert "555-0100" in body


def test_send_driver_details_confirmation_uses_tms_matched_phone_fallback() -> None:
    comms = MagicMock()
    comms.send_thread_reply.return_value = {
        "success": True,
        "communication_id": "comm-out-1",
    }
    svc = DriverAssignmentIngressService(communications_service=comms)
    settings = {
        "mikey_account_id": "acct-1",
        "driver_assignment": {
            "confirmation_email": {
                "turvo_app_template_html": "<p>{driver_name} {driver_phone}</p>",
            }
        },
    }
    result = svc.send_driver_details_confirmation_email(
        tenant_id=_TENANT_ID,
        tenant_settings=settings,
        payload={
            "tms_resolution": "found",
            "tms_driver_outcome": "assigned",
            "tms_is_tracking_customer": False,
            "tms_matched_driver_name": "Virat",
            "tms_matched_driver_phone": "9989239823",
            "workflow_lifecycle_id": _DRIVER_LC_ID,
            "thread_id": "thread-1",
            "driver_details_extraction": {
                "driver": {"name": "Virat", "phone": None},
            },
        },
        workflow_run_id="run-1",
    )
    assert result.sent is True
    body = comms.send_thread_reply.call_args.kwargs["body"]
    assert "Virat" in body
    assert "9989239823" in body
    assert "—" not in body
