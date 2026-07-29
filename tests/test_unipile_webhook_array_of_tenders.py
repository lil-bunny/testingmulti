"""Unipile webhook: ``data_import_id`` and ``array_of_tenders`` attachment to workflow payloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult
from app.services.ratecon_ingress_service import RateconIngressResult
from app.services.unipile_tenant_resolution import UnipileTenantContext


def _t3ra_tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid="aadc75f4-3f79-45d7-84c3-aa778e226e93",
        tenant_slug="t3ra",
    )


def _pod_classification_mock() -> MagicMock:
    classification = MagicMock()
    classification.workflow_name = "pod_lifecycle"
    return classification


def _ratecon_classification_mock() -> MagicMock:
    classification = MagicMock()
    classification.workflow_name = "ratecon"
    classification.to_ratecon_enqueue_payload.return_value = {
        "workflow_name": "ratecon",
        "load_id": "30389",
    }
    return classification


def _pod_prepare_result(*, workflow_payload: dict, is_duplicate: bool = False) -> MagicMock:
    return MagicMock(
        skipped=False,
        is_duplicate=is_duplicate,
        workflow_payload=workflow_payload,
    )


@pytest.fixture
def serialize_capture() -> list[dict]:
    return []


def _patch_serializer(serialize_capture: list[dict]):
    ser = MagicMock()

    def _resolve_then_enqueue(**kwargs: object) -> SerializeEnqueueResult:
        serialize_capture.append(dict(kwargs))  # type: ignore[arg-type]
        return SerializeEnqueueResult(
            lifecycle_id="lc-1",
            inbox_key="inbox:lifecycle:lc-1",
            status="started",
            celery_task_id="test-celery-task-id",
            workflow_lifecycle_id="lc-1",
        )

    ser.resolve_then_enqueue.side_effect = _resolve_then_enqueue
    return patch(
        "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService",
        return_value=ser,
    )


@pytest.mark.asyncio
async def test_t3ra_pod_omits_import_keys_when_no_import_id(
    serialize_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email",
            return_value=_pod_classification_mock(),
        ),
        _patch_serializer(serialize_capture),
    ):
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()
        ingress_service._pod_lifecycle_ingress.prepare_pod_email_received_for_ingress = AsyncMock(
            return_value=_pod_prepare_result(
                workflow_payload={
                    **RATECON_WEBHOOK_PAYLOAD,
                    "event_type": "email_received",
                    "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                }
            )
        )
        ingress_service._driver_details_email_ingress = MagicMock()
        ingress_service._driver_details_email_ingress.try_driver_details_email_received.return_value = None

        await ingress_service.process(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant=_t3ra_tenant(),
            communication_id="comm-1",
        )

    workflow_payload = serialize_capture[0]["payload"]
    assert "data_import_id" not in workflow_payload
    assert "array_of_tenders" not in workflow_payload


@pytest.mark.asyncio
async def test_t3ra_pod_carries_import_id_but_not_array_of_tenders(
    serialize_capture: list[dict],
) -> None:
    """Attachment import moved to graph prep; Ingress no longer stamps data_import_id."""
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email",
            return_value=_pod_classification_mock(),
        ),
        _patch_serializer(serialize_capture),
    ):
        ingress_service = T3raEmailIngressService()
        ingress_service._pod_lifecycle_ingress = MagicMock()
        ingress_service._pod_lifecycle_ingress.prepare_pod_email_received_for_ingress = AsyncMock(
            return_value=_pod_prepare_result(
                workflow_payload={
                    **RATECON_WEBHOOK_PAYLOAD,
                    "event_type": "email_received",
                    "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                }
            )
        )
        ingress_service._driver_details_email_ingress = MagicMock()
        ingress_service._driver_details_email_ingress.try_driver_details_email_received.return_value = None

        await ingress_service.process(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant=_t3ra_tenant(),
            communication_id="comm-1",
        )

    workflow_payload = serialize_capture[0]["payload"]
    # Graph task prep owns attachment import; Ingress path must not invent import keys.
    assert "data_import_id" not in workflow_payload
    assert "array_of_tenders" not in workflow_payload


@pytest.mark.asyncio
async def test_t3ra_ratecon_carries_event_type_email_received(
    serialize_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    with (
        patch(
            "app.services.t3ra_email_ingress_service.classify_t3ra_inbound_email",
            return_value=_ratecon_classification_mock(),
        ),
        patch(
            "app.services.ratecon_ingress_service.RateconIngressService.prepare_payload",
            new_callable=AsyncMock,
            return_value=RateconIngressResult(
                ok=True,
                payload={
                    **RATECON_WEBHOOK_PAYLOAD,
                    "workflow_name": "ratecon",
                    "load_id": "30389",
                    "shipment_id": "1000324895",
                    "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                },
            ),
        ),
        _patch_serializer(serialize_capture),
    ):
        ingress_service = T3raEmailIngressService()
        ingress_service._driver_details_email_ingress = MagicMock()
        ingress_service._driver_details_email_ingress.try_driver_details_email_received.return_value = None

        await ingress_service.process(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant=_t3ra_tenant(),
            communication_id="comm-1",
        )

    assert serialize_capture[0]["workflow_name"] == "ratecon"
    workflow_payload = serialize_capture[0]["payload"]
    assert workflow_payload["event_type"] == "email_received"
    assert workflow_payload["load_id"] == "30389"
