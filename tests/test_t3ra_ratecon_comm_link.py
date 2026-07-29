"""T3RA ingress passes communication_id into workflow payload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult
from app.services.ratecon_ingress_service import RateconIngressResult

_COMM_UUID = "11111111-2222-3333-4444-555555555555"
_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.asyncio
async def test_t3ra_ratecon_payload_includes_communication_id() -> None:
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService
    from app.services.unipile_tenant_resolution import UnipileTenantContext

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

    email_classification = MagicMock()
    email_classification.workflow_name = "ratecon"
    email_classification.to_ratecon_enqueue_payload.return_value = {
        "workflow_name": "ratecon",
        "load_id": "30389",
    }

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email",
            return_value=email_classification,
        ),
        patch(
            "app.services.ratecon_ingress_service.RateconIngressService.prepare_payload",
            new_callable=AsyncMock,
            return_value=RateconIngressResult(
                ok=True,
                payload={
                    **payload,
                    "workflow_name": "ratecon",
                    "load_id": "30389",
                    "shipment_id": "1000324895",
                    "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                },
            ),
        ),
        patch(
            "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService"
        ) as ser_cls,
    ):
        ser_cls.return_value.resolve_then_enqueue.return_value = SerializeEnqueueResult(
            lifecycle_id="ratecon-lc",
            inbox_key="inbox:lifecycle:ratecon-lc",
            status="started",
            celery_task_id="celery-1",
            workflow_lifecycle_id="ratecon-lc",
        )
        ingress_service = T3raEmailIngressService()
        ingress_service._driver_details_email_ingress = MagicMock()
        ingress_service._driver_details_email_ingress.try_driver_details_email_received.return_value = None

        result = await ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=_COMM_UUID,
        )

    assert result.outcome == "enqueued"
    ser_cls.return_value.resolve_then_enqueue.assert_called_once()
    kwargs = ser_cls.return_value.resolve_then_enqueue.call_args.kwargs
    assert kwargs["workflow_name"] == "ratecon"
    assert kwargs["payload"]["communication_id"] == _COMM_UUID
    assert kwargs["payload"]["event_type"] == "email_received"
