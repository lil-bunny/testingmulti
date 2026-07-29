"""Ratecon multi-stop ingress gate (pre-graph skip)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.ratecon_ingress_service import (
    RATECON_SKIP_MULTI_STOP,
    RateconIngressResult,
)
from app.services.workflow_service import WorkflowService


@pytest.mark.asyncio
async def test_workflow_service_ratecon_multi_stop_skips_graph(monkeypatch) -> None:
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    async def fake_prepare(**kwargs):
        return RateconIngressResult(
            ok=False,
            skip_reason=RATECON_SKIP_MULTI_STOP,
            payload={
                "load_id": "L1",
                "shipment_id": "99",
                "shipment": {
                    "details": {
                        "globalRoute": [{}, {}, {}],
                    }
                },
            },
        )

    monkeypatch.setattr(
        service._ratecon_ingress,
        "prepare_payload",
        AsyncMock(side_effect=fake_prepare),
    )
    run_impl = AsyncMock(return_value={"should_not": "run"})
    monkeypatch.setattr(service, "_run_impl", run_impl)
    monkeypatch.setattr(
        service.lifecycle_service,
        "resolve_or_create_lifecycle",
        MagicMock(side_effect=AssertionError("lifecycle must not run")),
    )

    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="ratecon",
        payload={"load_id": "L1"},
    )

    assert result["data"]["skipped_ratecon_ingress"] is True
    assert result["data"]["ratecon_ingress_skip_reason"] == RATECON_SKIP_MULTI_STOP
    run_impl.assert_not_called()
