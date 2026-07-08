"""Unipile webhook: ``data_import_id`` and ``array_of_tenders`` attachment to workflow payloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_classifier_service import WorkflowClassifierService


def _t3ra_tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid="aadc75f4-3f79-45d7-84c3-aa778e226e93",
        tenant_slug="t3ra",
    )


@pytest.fixture
def celery_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []
    mock_task = MagicMock()

    def apply_async(**kwargs: dict) -> MagicMock:
        captured.append(kwargs)
        out = MagicMock()
        out.id = "test-celery-task-id"
        return out

    mock_task.apply_async = apply_async
    monkeypatch.setattr(
        "app.services.t3ra_email_ingress_service.run_workflow_async", mock_task
    )
    return captured


@pytest.mark.asyncio
async def test_t3ra_pod_omits_import_keys_when_no_import_id(
    monkeypatch: pytest.MonkeyPatch,
    celery_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "pod_lifecycle"},
    )
    with patch(
        "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
        new_callable=AsyncMock,
        return_value=None,
    ):
        svc = T3raEmailIngressService()
        svc._pod_lifecycle_ingress = MagicMock()
        svc._pod_lifecycle_ingress.prepare_email_received_payload = AsyncMock(
            return_value={
                **RATECON_WEBHOOK_PAYLOAD,
                "event_type": "email_received",
                "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            }
        )
        svc._pod_lifecycle_ingress.is_duplicate_email_pod_ingest.return_value = False
        svc._driver_assignment_ingress = MagicMock()
        svc._driver_assignment_ingress.try_driver_details_email_received.return_value = None

        await svc.process(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant=_t3ra_tenant(),
            communication_id="comm-1",
        )

    wpayload = celery_capture[0]["kwargs"]["payload"]
    assert "data_import_id" not in wpayload
    assert "array_of_tenders" not in wpayload


@pytest.mark.asyncio
async def test_t3ra_pod_carries_import_id_but_not_array_of_tenders(
    monkeypatch: pytest.MonkeyPatch,
    celery_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "pod_lifecycle"},
    )
    with patch(
        "app.services.t3ra_email_ingress_service.process_email_webhook_attachment_import",
        new_callable=AsyncMock,
        return_value="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ):
        svc = T3raEmailIngressService()
        svc._pod_lifecycle_ingress = MagicMock()
        svc._pod_lifecycle_ingress.prepare_email_received_payload = AsyncMock(
            return_value={
                **RATECON_WEBHOOK_PAYLOAD,
                "event_type": "email_received",
                "shipments_row_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            }
        )
        svc._pod_lifecycle_ingress.is_duplicate_email_pod_ingest.return_value = False
        svc._driver_assignment_ingress = MagicMock()
        svc._driver_assignment_ingress.try_driver_details_email_received.return_value = None

        await svc.process(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant=_t3ra_tenant(),
            communication_id="comm-1",
        )

    wpayload = celery_capture[0]["kwargs"]["payload"]
    assert wpayload["data_import_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert "array_of_tenders" not in wpayload


@pytest.mark.asyncio
async def test_t3ra_ratecon_carries_event_type_email_received(
    monkeypatch: pytest.MonkeyPatch,
    celery_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
    from app.services.t3ra_email_ingress_service import T3raEmailIngressService

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "ratecon", "load_id": "30389"},
    )
    svc = T3raEmailIngressService()
    svc._driver_assignment_ingress = MagicMock()
    svc._driver_assignment_ingress.try_driver_details_email_received.return_value = None

    await svc.process(
        payload=RATECON_WEBHOOK_PAYLOAD,
        tenant=_t3ra_tenant(),
        communication_id="comm-1",
    )

    kwargs = celery_capture[0]["kwargs"]
    assert kwargs["workflow_name"] == "ratecon"
    wpayload = kwargs["payload"]
    assert wpayload["event_type"] == "email_received"
    assert wpayload["load_id"] == "30389"
