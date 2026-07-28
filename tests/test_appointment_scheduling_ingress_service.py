"""IngressService unit tests (cheap webhook gates + serializer enqueue)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.integrations.turvo.shipments import COVERED_STATUS_CODE_KEY
from app.integrations.turvo.webhook_mapping import TENDER_ACCEPTED_STATUS_CODE_KEY
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.ingress_service import IngressService
from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_SHIPMENT_ID = "12345"
_LOAD_ID = "47361"
_LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"
_SHIPMENTS_ROW_ID = "22222222-2222-2222-2222-222222222222"
_STUB_LIFECYCLE_ID = "44444444-4444-4444-4444-444444444444"


def _shipment_update_body(*, tender_accepted: bool = True) -> dict:
    status = (
        {
            "code": {
                "key": TENDER_ACCEPTED_STATUS_CODE_KEY,
                "value": "Tender - accepted",
            }
        }
        if tender_accepted
        else {"code": {"key": COVERED_STATUS_CODE_KEY, "value": "Covered"}}
    )
    return {
        "eventName": "SHIPMENT_UPDATE",
        "eventPayload": {
            "id": _SHIPMENT_ID,
            "load": {"id": _LOAD_ID},
            "status": status,
        },
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
    shipments_row: dict | None = None,
) -> IngressService:
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {
        "id": _TENANT_UUID,
        "settings": tenant_settings if tenant_settings is not None else _tenant_settings(),
    }

    lifecycle = MagicMock()
    lifecycle.find_blocking_appointment_scheduling_lifecycle_id.return_value = (
        blocking_lifecycle_id
    )
    lifecycle.deterministic_pickup_lifecycle_id.return_value = _STUB_LIFECYCLE_ID

    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = shipments_row

    return IngressService(
        tenants_service=tenants,
        lifecycle_service=lifecycle,
        shipments_service=shipments,
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
async def test_handle_shipment_update_skips_when_status_not_tender_accepted() -> None:
    svc = _service()
    result = await svc.handle_shipment_update(
        _shipment_update_body(tender_accepted=False),
        _TENANT_SLUG,
    )
    assert result.skip_reason == "status_not_tender_accepted"


@pytest.mark.asyncio
async def test_handle_shipment_update_skips_duplicate_lifecycle() -> None:
    svc = _service(blocking_lifecycle_id=_LIFECYCLE_ID)
    result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)
    assert result.skip_reason == "duplicate_lifecycle"


@pytest.mark.asyncio
async def test_handle_shipment_update_resolve_then_enqueue_when_shipments_row_exists() -> None:
    svc = _service(
        shipments_row={"id": _SHIPMENTS_ROW_ID, "shipment_number": _SHIPMENT_ID},
    )
    serialize_result = SerializeEnqueueResult(
        lifecycle_id=_LIFECYCLE_ID,
        inbox_key="inbox",
        status="started",
        celery_task_id="celery-task-1",
    )

    with patch(
        "app.services.appointment_scheduling.ingress_service.LifecycleRunSerializerService"
    ) as serializer_cls:
        serializer_cls.return_value.resolve_then_enqueue.return_value = serialize_result
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.enqueued is True
    assert result.execution_id
    serializer_cls.return_value.resolve_then_enqueue.assert_called_once()
    serializer_cls.return_value.enqueue.assert_not_called()
    kwargs = serializer_cls.return_value.resolve_then_enqueue.call_args.kwargs
    assert kwargs["payload"]["shipments_row_id"] == _SHIPMENTS_ROW_ID
    assert kwargs["payload"]["event_type"] == WorkflowRunEventType.TURVO_PICKUP_CHANGED.value


@pytest.mark.asyncio
async def test_handle_shipment_update_enqueue_stub_when_no_shipments_row() -> None:
    svc = _service(shipments_row=None)
    serialize_result = SerializeEnqueueResult(
        lifecycle_id=_STUB_LIFECYCLE_ID,
        inbox_key="inbox",
        status="buffered",
        celery_task_id=None,
    )

    with patch(
        "app.services.appointment_scheduling.ingress_service.LifecycleRunSerializerService"
    ) as serializer_cls:
        serializer_cls.return_value.enqueue.return_value = serialize_result
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.enqueued is True
    assert result.execution_id
    svc._lifecycle.deterministic_pickup_lifecycle_id.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_number=_SHIPMENT_ID,
    )
    svc._lifecycle.ensure_pickup_ingress_lifecycle_stub.assert_not_called()
    serializer_cls.return_value.enqueue.assert_called_once()
    payload = serializer_cls.return_value.enqueue.call_args.kwargs["payload"]
    assert payload["workflow_lifecycle_id"] == _STUB_LIFECYCLE_ID


@pytest.mark.asyncio
async def test_handle_shipment_update_enqueue_failed() -> None:
    svc = _service()
    with patch(
        "app.services.appointment_scheduling.ingress_service.LifecycleRunSerializerService",
        side_effect=RuntimeError("broker down"),
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.handled is True
    assert result.enqueued is False
    assert result.skip_reason == "enqueue_failed"
