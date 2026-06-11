"""T3RA ingress passes communication_id into workflow payload."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status

_COMM_UUID = "11111111-2222-3333-4444-555555555555"
_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _load_t3ra_service(monkeypatch):
    celery_mock = MagicMock()
    celery_mock.apply_async.return_value = MagicMock(id="celery-1")
    workflows_mod = MagicMock()
    workflows_mod.run_workflow_async = celery_mock
    monkeypatch.setitem(sys.modules, "app.tasks.workflows", workflows_mod)
    sys.modules.pop("app.services.t3ra_inbound_email_service", None)
    from app.services.t3ra_inbound_email_service import T3raInboundEmailService

    return T3raInboundEmailService, celery_mock


@pytest.mark.asyncio
async def test_t3ra_ratecon_payload_includes_communication_id(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    T3raInboundEmailService, celery_task = _load_t3ra_service(monkeypatch)
    tenant = UnipileTenantContext(
        tenant_uuid=_TENANT_UUID,
        tenant_slug="t3ra",
    )
    payload = {
        "webhook_name": "t3ra-inbox",
        "subject": "Rate confirmation load 30389",
        "has_attachments": True,
        "thread_id": "thread-abc",
    }

    with patch(
        "app.services.t3ra_inbound_email_service.WorkflowClassifierService"
    ) as cls:
        svc = T3raInboundEmailService()
        svc._communications = MagicMock()
        svc._communications.record_or_resolve_inbound.return_value = _COMM_UUID
        cls.return_value.classify_workflow_type.return_value = {
            "workflow_name": "ratecon",
            "load_id": "30389",
        }

        resp = await svc.handle(payload=payload, tenant=tenant)

    assert resp.status_code == status.HTTP_200_OK
    celery_kw = celery_task.apply_async.call_args.kwargs["kwargs"]
    assert celery_kw["workflow_name"] == "ratecon"
    assert celery_kw["payload"]["communication_id"] == _COMM_UUID
    assert celery_kw["payload"]["event_type"] == "email_received"
