"""T3RA inbound email routing: POD before driver details."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.ingress_result import IngressResult
from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_COMM_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.mark.asyncio
async def test_t3ra_pod_classification_skips_driver_details() -> None:
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    return T3raEmailIngressService


@pytest.mark.asyncio
async def test_t3ra_appointment_reply_enqueued_before_driver_details_and_ratecon() -> None:
    """Appointment customer-reply L2 runs before driver details / ratecon (§5.2)."""
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": 'Re: DEL APPT REQ "63294"',
        "body": "Confirmed July 18 10:30 AM",
        "thread_id": "thread-appt-1",
        "in_reply_to": "msg-parent",
    }
    appointment_result = IngressResult(
        outcome="enqueued",
        event_type="appointment_customer_reply_received",
        execution_ids=("exec-appt-1",),
    )

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email"
        ) as classify_mock,
        patch(
            "app.services.appointment_scheduling.customer_reply_ingress.CustomerReplyIngressService"
        ) as reply_cls,
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        classify_mock.return_value = MagicMock(workflow_name="ratecon")
        reply_cls.return_value.try_customer_reply_received.return_value = appointment_result
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    assert result.execution_ids == ("exec-appt-1",)
    reply_cls.return_value.try_customer_reply_received.assert_called_once()
    driver_details_cls.return_value.try_driver_details_email_received.assert_not_called()


@pytest.mark.asyncio
async def test_t3ra_pod_classification_skips_driver_details(monkeypatch) -> None:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

    tenant = UnipileTenantContext(tenant_uuid=_TENANT_UUID, tenant_slug="t3ra")
    payload = {
        "subject": "POD load 30389",
        "has_attachments": True,
        "thread_id": "thread-1",
        "in_reply_to": "msg-parent",
        "email_id": "mail-pod-1",
    }

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email"
        ) as classify_mock,
        patch(
            "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService"
        ) as ser_cls,
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        ser_cls.return_value.resolve_then_enqueue.return_value = SerializeEnqueueResult(
            lifecycle_id="pod-lc",
            inbox_key="inbox:lifecycle:pod-lc",
            status="started",
            celery_task_id="celery-1",
            workflow_lifecycle_id="pod-lc",
        )
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
    ser_cls.return_value.resolve_then_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_t3ra_driver_details_reply_enqueued_before_ratecon() -> None:
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService
    from app.services.unipile_tenant_resolution import UnipileTenantContext

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
            "app.services.appointment_scheduling.customer_reply_ingress.CustomerReplyIngressService"
        ) as reply_cls,
        patch(
            "app.services.t3ra_email_ingress_service.DriverDetailsEmailIngressService"
        ) as driver_details_cls,
    ):
        classify_mock.return_value = MagicMock(workflow_name=None)
        reply_cls.return_value.try_customer_reply_received.return_value = None
        driver_details_cls.return_value.try_driver_details_email_received.return_value = (
            driver_details_result
        )
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    assert result.execution_ids == ("exec-driver-1",)
    reply_cls.return_value.try_customer_reply_received.assert_called_once()
    driver_details_cls.return_value.try_driver_details_email_received.assert_called_once()


@pytest.mark.asyncio
async def test_t3ra_pod_ingress_skip_without_celery() -> None:
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService
    from app.services.unipile_tenant_resolution import UnipileTenantContext

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
            "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService"
        ) as ser_cls,
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
    ser_cls.return_value.resolve_then_enqueue.assert_not_called()
    driver_details_cls.return_value.try_driver_details_email_received.assert_not_called()
