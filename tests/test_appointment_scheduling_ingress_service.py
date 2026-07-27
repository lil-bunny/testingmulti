"""IngressService unit tests (cheap webhook gates + enqueue only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.integrations.turvo.shipments import COVERED_STATUS_CODE_KEY
from app.integrations.turvo.webhook_mapping import TENDER_ACCEPTED_STATUS_CODE_KEY
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.ingress_service import IngressService
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_SHIPMENT_ID = "12345"
_LOAD_ID = "47361"
_LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"


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

    return IngressService(
        tenants_service=tenants,
        lifecycle_service=lifecycle,
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
async def test_handle_shipment_update_happy_path_enqueues_slim_payload() -> None:
    svc = _service()
    celery_task = MagicMock(id="celery-task-1")

    with patch(
        "app.services.appointment_scheduling.ingress_service.run_workflow_async.apply_async",
        return_value=celery_task,
    ) as apply_async:
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
    assert payload["tenant_id"] == _TENANT_UUID
    assert payload["tenant_slug"] == _TENANT_SLUG
    assert "shipment" not in payload
    assert "workflow_lifecycle_id" not in payload
    assert "shipments_row_id" not in payload
    assert "reference_number" not in payload


@pytest.mark.asyncio
async def test_handle_shipment_update_enqueue_failed_does_not_create_lifecycle() -> None:
    svc = _service()
    with patch(
        "app.services.appointment_scheduling.ingress_service.enqueue_appointment_scheduling_pickup_changed",
        side_effect=RuntimeError("broker down"),
    ):
        result = await svc.handle_shipment_update(_shipment_update_body(), _TENANT_SLUG)

    assert result.handled is True
    assert result.enqueued is False
    assert result.skip_reason == "enqueue_failed"
