"""WorkflowService pickup-changed pre-graph prepare tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.appointment_scheduling.ingress_prepare_service import IngressPrepareResult
from app.services.workflow_service import WorkflowService
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
_LIFECYCLE_ID = "11111111-1111-1111-1111-111111111111"
_SHIPMENTS_ROW_ID = "22222222-2222-2222-2222-222222222222"


def _mock_t3ra_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "id": _TENANT_UUID,
        "slug": "t3ra",
        "settings": minimal_t3ra_tenant_settings(),
    }
    monkeypatch.setattr(
        "app.services.tenants_service.TenantsService.get_by_slug",
        lambda self, slug: row if slug == "t3ra" else None,
    )


@pytest.mark.asyncio
async def test_pickup_prepare_skip_does_not_invoke_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_t3ra_tenant(monkeypatch)
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    with patch(
        "app.services.appointment_scheduling.ingress_prepare_service.IngressPrepareService"
    ) as prep_cls:
        prep_cls.return_value.prepare_pickup_changed = AsyncMock(
            return_value=IngressPrepareResult(
                ok=False,
                skip_reason="non_diamond_customer",
            )
        )
        with patch.object(service, "_run_impl", new_callable=AsyncMock) as run_impl:
            result = await service.run(
                tenant_slug="t3ra",
                workflow_name="appointment_scheduling",
                payload={
                    "event_type": "turvo_pickup_changed",
                    "workflow_lifecycle_id": _LIFECYCLE_ID,
                    "shipment_id": "12345",
                    "execution_id": "exec-1",
                },
            )

    run_impl.assert_not_called()
    assert result["data"]["pickup_ingress_skip_reason"] == "non_diamond_customer"


@pytest.mark.asyncio
async def test_pickup_prepare_ok_invokes_graph_with_merged_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_t3ra_tenant(monkeypatch)
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    with patch(
        "app.services.appointment_scheduling.ingress_prepare_service.IngressPrepareService"
    ) as prep_cls:
        prep_cls.return_value.prepare_pickup_changed = AsyncMock(
            return_value=IngressPrepareResult(
                ok=True,
                workflow_lifecycle_id=_LIFECYCLE_ID,
                shipments_row_id=_SHIPMENTS_ROW_ID,
                reference_number="REF-1",
                load_id="load-1",
                customer_name="Costco",
            )
        )
        with patch("app.services.workflow_service.traceable", lambda **_kw: lambda fn: fn):
            with patch.object(service, "_run_impl", new_callable=AsyncMock) as run_impl:
                run_impl.return_value = {"ok": True}
                await service.run(
                    tenant_slug="t3ra",
                    workflow_name="appointment_scheduling",
                    payload={
                        "event_type": "turvo_pickup_changed",
                        "workflow_lifecycle_id": _LIFECYCLE_ID,
                        "shipment_id": "12345",
                        "execution_id": "exec-1",
                    },
                )

    run_impl.assert_called_once()
    payload = run_impl.call_args.kwargs["payload"]
    assert payload["shipments_row_id"] == _SHIPMENTS_ROW_ID
    assert payload["reference_number"] == "REF-1"
    assert payload["load_id"] == "load-1"
    assert payload["customer_name"] == "Costco"


def test_deterministic_pickup_lifecycle_id_is_stable() -> None:
    from app.services.workflow_lifecycle_service import WorkflowLifecycleService

    svc = WorkflowLifecycleService()
    first = svc.deterministic_pickup_lifecycle_id(
        tenant_id=_TENANT_UUID,
        shipment_number="12345",
    )
    second = svc.deterministic_pickup_lifecycle_id(
        tenant_id=_TENANT_UUID,
        shipment_number="12345",
    )
    other = svc.deterministic_pickup_lifecycle_id(
        tenant_id=_TENANT_UUID,
        shipment_number="99999",
    )
    assert first == second
    assert first != other
