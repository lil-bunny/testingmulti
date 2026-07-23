"""AppointmentSchedulingIngressService unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.ingress_service import AppointmentSchedulingIngressService
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_SHIPMENT_ID = "12345"
_LOAD_ID = "47361"
_SHIPMENTS_ROW_ID = "22222222-2222-2222-2222-222222222222"
_LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"


def _shipment_update_body(*, tender_accepted: bool = True) -> dict:
    status = (
        {"code": {"value": "Tender-Accepted"}}
        if tender_accepted
        else {"code": {"value": "Covered"}}
    )
    return {
        "eventName": "SHIPMENT_UPDATE",
        "eventPayload": {
            "id": _SHIPMENT_ID,
            "load": {"id": _LOAD_ID},
            "status": status,
        },
    }


def _activity_json(*, pickup_changed: bool = True) -> dict:
    prev_date = "2026-03-20"
    final_date = "2026-03-21" if pickup_changed else prev_date
    return {
        "data": [
            {
                "record_metadata": {"created_by": {"name": "Ops User"}},
                "context_snapshot": {
                    "global_route": {"ship_locations": [{"type": {"key": "1500"}}, {}]},
                    "delta": {
                        "prev_diff_context": {
                            "global_route": {
                                "ship_locations": [
                                    {
                                        "type": {"key": "1500"},
                                        "appointment": {"date": prev_date},
                                    }
                                ]
                            }
                        },
                        "final_diff_context": {
                            "global_route": {
                                "ship_locations": [
                                    {
                                        "type": {"key": "1500"},
                                        "appointment": {"date": final_date},
                                    }
                                ]
                            }
                        },
                    },
                },
            }
        ]
    }


def _turvo_shipment_payload(
    *,
    reference: str = "DIAMOND-RPN-999",
    global_route: list[dict] | None = None,
) -> dict:
    route = global_route
    if route is None:
        route = [
            {
                "deleted": False,
                "name": "Acme Pickup",
                "stopType": {"value": "Pickup"},
            },
            {
                "deleted": False,
                "name": "PETCO DC 810",
                "stopType": {"value": "Delivery"},
            },
        ]
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Acme Corp", "id": "CUST-1"},
                    "externalIds": [{"idValue": reference}],
                }
            ],
            "customId": _LOAD_ID,
            "globalRoute": route,
        }
    }


def _tenant_settings(*, enabled: bool = True) -> dict:
    settings = minimal_t3ra_tenant_settings()
    processes = list(settings.get("enabledProcesses") or [])
    if enabled and "appointment_scheduling" not in processes:
        processes.append("appointment_scheduling")
    if not enabled:
        processes = [p for p in processes if p != "appointment_scheduling"]
    settings["enabledProcesses"] = processes
    return settings


def _service(
    *,
    tenant_settings: dict | None = None,
    blocking_lifecycle_id: str | None = None,
    prepare_ok: bool = True,
    prepare_skip_reason: str | None = None,
) -> AppointmentSchedulingIngressService:
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {
        "id": _TENANT_UUID,
        "settings": tenant_settings if tenant_settings is not None else _tenant_settings(),
    }

    lifecycle = MagicMock()
    lifecycle.find_blocking_appointment_scheduling_lifecycle_id.return_value = (
        blocking_lifecycle_id
    )

    prepare = MagicMock()
    if prepare_ok:
        contact = MagicMock()
        contact.model_dump.return_value = {"email": "wh@example.com", "customer": "PETCO DC 810"}
        prepare.prepare_pickup_changed.return_value = MagicMock(
            ok=True,
            skip_reason=None,
            workflow_lifecycle_id=_LIFECYCLE_ID,
            shipments_row_id=_SHIPMENTS_ROW_ID,
            customer_name="PETCO DC 810",
            customer_contact=contact,
        )
    else:
        prepare.prepare_pickup_changed.return_value = MagicMock(
            ok=False,
            skip_reason=prepare_skip_reason or "missing_recipient_email",
            workflow_lifecycle_id=None,
            shipments_row_id=None,
            customer_name=None,
            customer_contact=None,
        )

    scheduling_lifecycle = MagicMock()

    return AppointmentSchedulingIngressService(
        tenants_service=tenants,
        lifecycle_service=lifecycle,
        prepare_service=prepare,
        scheduling_lifecycle_service=scheduling_lifecycle,
    )


@pytest.mark.asyncio
async def test_handle_shipment_update_not_handled_for_unrelated_event() -> None:
    svc = _service()
    result = await svc.handle_shipment_update({"eventName": "OTHER"}, _TENANT_SLUG)
    assert result.handled is False
    assert result.enqueued is False


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_when_process_disabled() -> None:
    svc = _service(tenant_settings=_tenant_settings(enabled=False))
    result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)
    assert result.handled is True
    assert result.enqueued is False
    assert result.skip_reason == "process_disabled"


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_duplicate_lifecycle() -> None:
    svc = _service(blocking_lifecycle_id=_LIFECYCLE_ID)
    result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)
    assert result.skip_reason == "duplicate_lifecycle"


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_non_diamond_reference() -> None:
    svc = _service()
    with (
        patch(
            "app.services.appointment_scheduling.ingress_service.fetch_shipment_activity_list",
            new=AsyncMock(return_value=_activity_json()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.get_shipment",
            new=AsyncMock(return_value=_turvo_shipment_payload(reference="ACME-1")),
        ),
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.skip_reason == "non_diamond_customer"


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_multi_stop_from_shipment_not_activity() -> None:
    from tests.test_shipment_location_link import THREE_STOP_ROUTE

    svc = _service()
    activity_mock = AsyncMock(return_value=_activity_json())
    with (
        patch(
            "app.services.appointment_scheduling.ingress_service.get_shipment",
            new=AsyncMock(
                return_value=_turvo_shipment_payload(global_route=THREE_STOP_ROUTE),
            ),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.fetch_shipment_activity_list",
            new=activity_mock,
        ),
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.handled is True
    assert result.enqueued is False
    assert result.skip_reason == "multi_stop"
    activity_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_shipment_update_happy_path_enqueues() -> None:
    svc = _service()
    celery_task = MagicMock(id="celery-task-1")

    with (
        patch(
            "app.services.appointment_scheduling.ingress_service.fetch_shipment_activity_list",
            new=AsyncMock(return_value=_activity_json()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.get_shipment",
            new=AsyncMock(return_value=_turvo_shipment_payload()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.run_workflow_async.apply_async",
            return_value=celery_task,
        ) as apply_async,
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.enqueued is True
    assert result.execution_id
    apply_async.assert_called_once()
    kwargs = apply_async.call_args.kwargs["kwargs"]
    assert kwargs["workflow_name"] == "appointment_scheduling"
    payload = kwargs["payload"]
    assert payload["event_type"] == WorkflowRunEventType.TURVO_PICKUP_CHANGED.value
    assert payload["shipment_id"] == _SHIPMENT_ID
    assert payload["load_id"] == _LOAD_ID
    assert payload["reference_number"] == "DIAMOND-RPN-999"
    assert "shipment" not in payload
    assert payload["workflow_lifecycle_id"] == _LIFECYCLE_ID
    assert payload["shipments_row_id"] == _SHIPMENTS_ROW_ID
    svc._prepare.prepare_pickup_changed.assert_called_once()


@pytest.mark.asyncio
async def test_handle_shipment_update_enqueue_failed_marks_lifecycle_restartable() -> None:
    svc = _service()
    with (
        patch(
            "app.services.appointment_scheduling.ingress_service.fetch_shipment_activity_list",
            new=AsyncMock(return_value=_activity_json()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.get_shipment",
            new=AsyncMock(return_value=_turvo_shipment_payload()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.enqueue_appointment_scheduling_pickup_changed",
            side_effect=RuntimeError("broker down"),
        ),
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.handled is True
    assert result.enqueued is False
    assert result.skip_reason == "enqueue_failed"
    svc._scheduling_lifecycle.mark_restartable_skip.assert_called_once_with(
        _LIFECYCLE_ID,
        "enqueue_failed",
        tenant_id=_TENANT_UUID,
    )


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_before_prepare_when_sheet_gate_fails() -> None:
    svc = _service(prepare_ok=False, prepare_skip_reason="missing_recipient_email")
    with (
        patch(
            "app.services.appointment_scheduling.ingress_service.fetch_shipment_activity_list",
            new=AsyncMock(return_value=_activity_json()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.get_shipment",
            new=AsyncMock(return_value=_turvo_shipment_payload()),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_service.enqueue_appointment_scheduling_pickup_changed",
        ) as enqueue_mock,
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.skip_reason == "missing_recipient_email"
    enqueue_mock.assert_not_called()
    svc._scheduling_lifecycle.mark_restartable_skip.assert_not_called()
