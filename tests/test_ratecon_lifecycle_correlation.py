"""Ratecon lifecycle correlation: shipment FK before load_id."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_find_existing_lifecycle_id_ratecon_skips_load_id(monkeypatch) -> None:
    repo = WorkflowLifecyclesRepository(MagicMock())
    predicates: list[str] = []

    def fake_fetch(**kwargs):
        predicates.append(kwargs.get("extra_predicate", ""))
        if "shipment_id" in kwargs.get("extra_predicate", ""):
            return "lc-ship"
        return None

    monkeypatch.setattr(repo, "_fetch_lifecycle_id", fake_fetch)

    found = repo.find_existing_lifecycle_id(
        tenant_id="tenant-uuid",
        workflow_name="ratecon",
        load_id="56368",
        shipment_id=_ROW_UUID,
        thread_id="thread-1",
    )
    assert found == "lc-ship"
    assert any("shipment_id" in p for p in predicates)
    assert not any("load_id" in p for p in predicates)


def test_resolve_or_create_ratecon_passes_no_load_id() -> None:
    repo = MagicMock()
    repo.resolve_or_create.return_value = ("lc-1", False)
    svc = WorkflowLifecycleService(lifecycles_repository=repo)
    tenant_uuid = "00000000-0000-4000-8000-0000000000e1"

    with patch(
        "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
        return_value=tenant_uuid,
    ):
        svc.resolve_or_create_lifecycle(
            tenant_id=tenant_uuid,
            workflow_name="ratecon",
            payload={
                "load_id": "56368",
                "shipments_row_id": _ROW_UUID,
                "thread_id": "thread-1",
            },
        )

    repo.resolve_or_create.assert_called_once()
    kwargs = repo.resolve_or_create.call_args.kwargs
    assert kwargs["load_id"] is None
    assert kwargs["shipment_id"] == _ROW_UUID
    assert kwargs["thread_id"] == "thread-1"


def test_extract_load_id_none_for_ratecon() -> None:
    assert (
        WorkflowLifecycleService._extract_load_id(
            {"load_id": "56368"}, workflow_name="ratecon"
        )
        is None
    )


def test_extract_load_id_still_used_for_load_tendering() -> None:
    assert (
        WorkflowLifecycleService._extract_load_id(
            {"load_id": "ORD-1"}, workflow_name="load_tendering"
        )
        == "ORD-1"
    )
