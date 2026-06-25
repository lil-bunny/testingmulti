"""T3RA inbound email routing: POD before driver details."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_COMM_UUID = "11111111-2222-3333-4444-555555555555"


def _load_t3ra_service(monkeypatch):
    celery_mock = MagicMock()
    celery_mock.apply_async.return_value = MagicMock(id="celery-1")
    workflows_mod = MagicMock()
    workflows_mod.run_workflow_async = celery_mock
    monkeypatch.setitem(sys.modules, "app.tasks.workflows", workflows_mod)
    sys.modules.pop("app.services.t3ra_inbound_email_service", None)
    from app.services.t3ra_inbound_email_service import T3raInboundEmailService

    return T3raInboundEmailService


@pytest.mark.asyncio
async def test_t3ra_pod_classification_skips_driver_details(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    T3raInboundEmailService = _load_t3ra_service(monkeypatch)
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "POD load 30389",
        "has_attachments": True,
        "thread_id": "thread-1",
        "in_reply_to": "msg-parent",
    }

    with (
        patch(
            "app.services.t3ra_inbound_email_service.WorkflowClassifierService"
        ) as cls,
        patch(
            "app.services.t3ra_inbound_email_service.process_email_webhook_attachment_import",
            new_callable=AsyncMock,
            return_value="import-1",
        ),
        patch(
            "app.services.t3ra_inbound_email_service.DriverAssignmentIngressService"
        ) as driver_cls,
    ):
        svc = T3raInboundEmailService()
        svc._communications = MagicMock()
        svc._communications.record_or_resolve_inbound.return_value = _COMM_UUID
        cls.return_value.classify_workflow_type.return_value = {
            "workflow_name": "pod_lifecycle",
        }
        driver_ingress = driver_cls.return_value

        resp = await svc.handle(payload=payload, tenant=tenant)

    assert resp.status_code == status.HTTP_200_OK
    driver_ingress.try_driver_details_email_received.assert_not_called()


@pytest.mark.asyncio
async def test_t3ra_driver_details_reply_enqueued_before_ratecon(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext
    from fastapi.responses import JSONResponse

    T3raInboundEmailService = _load_t3ra_service(monkeypatch)
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "Re: driver info",
        "body": "Driver John 555-0100",
        "thread_id": "thread-1",
        "in_reply_to": "msg-parent",
    }
    driver_response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"message": "success", "event_type": "driver_details_email_received"},
    )

    with (
        patch(
            "app.services.t3ra_inbound_email_service.WorkflowClassifierService"
        ) as cls,
        patch(
            "app.services.t3ra_inbound_email_service.DriverAssignmentIngressService"
        ) as driver_cls,
    ):
        svc = T3raInboundEmailService()
        svc._communications = MagicMock()
        svc._communications.record_or_resolve_inbound.return_value = _COMM_UUID
        cls.return_value.classify_workflow_type.return_value = None
        driver_cls.return_value.try_driver_details_email_received.return_value = (
            driver_response
        )

        resp = await svc.handle(payload=payload, tenant=tenant)

    assert resp is driver_response
    driver_cls.return_value.try_driver_details_email_received.assert_called_once()
