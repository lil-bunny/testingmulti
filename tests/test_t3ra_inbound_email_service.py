"""T3RA inbound email routing: POD before driver details."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.ingress_result import IngressResult

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_COMM_UUID = "11111111-2222-3333-4444-555555555555"


def _load_t3ra_service(monkeypatch):
    celery_mock = MagicMock()
    celery_mock.apply_async.return_value = MagicMock(id="celery-1")
    workflows_mod = MagicMock()
    workflows_mod.run_workflow_async = celery_mock
    monkeypatch.setitem(sys.modules, "app.tasks.workflows", workflows_mod)
    sys.modules.pop("app.services.t3ra_email_ingress_service", None)
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    return T3raEmailIngressService


@pytest.mark.asyncio
async def test_t3ra_pod_classification_skips_driver_details(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    T3raEmailIngressService = _load_t3ra_service(monkeypatch)
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "POD load 30389",
        "has_attachments": True,
        "thread_id": "thread-1",
        "in_reply_to": "msg-parent",
    }

    with (
        patch(
            "app.services.t3ra_email_ingress_service.WorkflowClassifierService"
        ) as cls,
        patch(
            "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
            new_callable=AsyncMock,
            return_value="import-1",
        ),
        patch(
            "app.services.t3ra_email_ingress_service.DriverAssignmentIngressService"
        ) as driver_cls,
    ):
        svc = T3raEmailIngressService()
        svc._pod_lifecycle_ingress = MagicMock()
        svc._pod_lifecycle_ingress.prepare_email_received_payload = AsyncMock(
            return_value={
                **payload,
                "event_type": "email_received",
                "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "shipment_id": "1000324895",
            }
        )
        svc._pod_lifecycle_ingress.is_duplicate_email_pod_ingest.return_value = False
        cls.return_value.classify_workflow_type.return_value = {
            "workflow_name": "pod_lifecycle",
        }
        driver_ingress = driver_cls.return_value

        result = await svc.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    driver_ingress.try_driver_details_email_received.assert_not_called()


@pytest.mark.asyncio
async def test_t3ra_driver_details_reply_enqueued_before_ratecon(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    T3raEmailIngressService = _load_t3ra_service(monkeypatch)
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "Re: driver info",
        "body": "Driver John 555-0100",
        "thread_id": "thread-1",
        "in_reply_to": "msg-parent",
    }
    driver_result = IngressResult(
        outcome="enqueued",
        event_type="driver_details_email_received",
        execution_ids=("exec-driver-1",),
    )

    with (
        patch(
            "app.services.t3ra_email_ingress_service.WorkflowClassifierService"
        ) as cls,
        patch(
            "app.services.t3ra_email_ingress_service.DriverAssignmentIngressService"
        ) as driver_cls,
    ):
        svc = T3raEmailIngressService()
        cls.return_value.classify_workflow_type.return_value = None
        driver_cls.return_value.try_driver_details_email_received.return_value = (
            driver_result
        )

        result = await svc.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    assert result.execution_ids == ("exec-driver-1",)
    driver_cls.return_value.try_driver_details_email_received.assert_called_once()


@pytest.mark.asyncio
async def test_t3ra_pod_ingress_skip_without_celery(monkeypatch) -> None:
    from app.services.pod_lifecycle_ingress_service import PodEmailIngressSkipped
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    T3raEmailIngressService = _load_t3ra_service(monkeypatch)
    celery_mock = sys.modules["app.tasks.workflows"].run_workflow_async
    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "POD load 62495",
        "has_attachments": True,
        "thread_id": "orphan-thread",
        "attachments": [{"name": "62495 bol.pdf", "mime": "application/pdf"}],
    }

    with (
        patch(
            "app.services.t3ra_email_ingress_service.WorkflowClassifierService"
        ) as cls,
        patch(
            "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
            new_callable=AsyncMock,
        ) as attachment_import,
        patch(
            "app.services.t3ra_email_ingress_service.DriverAssignmentIngressService"
        ) as driver_cls,
    ):
        svc = T3raEmailIngressService()
        svc._pod_lifecycle_ingress = MagicMock()
        svc._pod_lifecycle_ingress.prepare_email_received_payload = AsyncMock(
            side_effect=PodEmailIngressSkipped("no_shipment_context")
        )
        cls.return_value.classify_workflow_type.return_value = {
            "workflow_name": "pod_lifecycle",
        }

        result = await svc.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "skipped"
    assert result.reason == "no_shipment_context"
    attachment_import.assert_not_called()
    celery_mock.apply_async.assert_not_called()
    driver_cls.return_value.try_driver_details_email_received.assert_not_called()
