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
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email"
        ) as classify_mock,
        patch(
            "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
            new_callable=AsyncMock,
            return_value="import-1",
        ),
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()
        ingress_service._pod_lifecycle_ingress.prepare_pod_email_received_for_ingress = AsyncMock(
            return_value=MagicMock(
                skipped=False,
                is_duplicate=False,
                workflow_payload={
                    **payload,
                    "event_type": "email_received",
                    "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "shipment_id": "1000324895",
                },
            )
        )
        classify_mock.return_value = MagicMock(workflow_name="pod_lifecycle")
        driver_details_ingress = driver_details_cls.return_value

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    driver_details_ingress.try_driver_details_email_received.assert_not_called()


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
    driver_details_result = IngressResult(
        outcome="enqueued",
        event_type="driver_details_email_received",
        execution_ids=("exec-driver-1",),
    )

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email"
        ) as classify_mock,
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        ingress_service = T3raEmailIngressService()
        classify_mock.return_value = MagicMock(workflow_name=None)
        driver_details_cls.return_value.try_driver_details_email_received.return_value = (
            driver_details_result
        )

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    assert result.execution_ids == ("exec-driver-1",)
    driver_details_cls.return_value.try_driver_details_email_received.assert_called_once()


@pytest.mark.asyncio
async def test_t3ra_pod_ingress_skip_without_celery(monkeypatch) -> None:
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
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email"
        ) as classify_mock,
        patch(
            "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
            new_callable=AsyncMock,
        ) as attachment_import,
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()
        ingress_service._pod_lifecycle_ingress.prepare_pod_email_received_for_ingress = AsyncMock(
            return_value=MagicMock(
                skipped=True,
                skip_reason="no_shipment_context",
                shipments_row_id=None,
                is_duplicate=False,
                workflow_payload=None,
            )
        )
        classify_mock.return_value = MagicMock(workflow_name="pod_lifecycle")

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "skipped"
    assert result.reason == "no_shipment_context"
    attachment_import.assert_not_called()
    celery_mock.apply_async.assert_not_called()
    driver_details_cls.return_value.try_driver_details_email_received.assert_not_called()
