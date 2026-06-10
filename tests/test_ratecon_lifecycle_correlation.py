"""Ratecon / pod_lifecycle correlation: shipment FK first, no load_id on lifecycles."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_find_existing_lifecycle_id_ratecon_shipment_first(monkeypatch) -> None:
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
        shipment_id=_ROW_UUID,
        thread_id="thread-1",
    )
    assert found == "lc-ship"
    assert any("shipment_id" in p for p in predicates)
    assert not any("load_id" in p for p in predicates)


def test_find_existing_lifecycle_id_pod_lifecycle_shipment_first(monkeypatch) -> None:
    repo = WorkflowLifecyclesRepository(MagicMock())
    call_order: list[str] = []

    def fake_fetch(**kwargs):
        pred = kwargs.get("extra_predicate", "")
        if "shipment_id" in pred:
            call_order.append("shipment")
            return "lc-pod"
        if "email_thread_id" in pred:
            call_order.append("thread")
        return None

    monkeypatch.setattr(repo, "_fetch_lifecycle_id", fake_fetch)

    found = repo.find_existing_lifecycle_id(
        tenant_id="tenant-uuid",
        workflow_name="pod_lifecycle",
        shipment_id=_ROW_UUID,
        thread_id="thread-1",
    )
    assert found == "lc-pod"
    assert call_order == ["shipment"]


def test_resolve_or_create_ratecon_passes_shipment_uuid() -> None:
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
    assert kwargs["shipment_id"] == _ROW_UUID
    assert kwargs["thread_id"] is None
    assert "load_id" not in kwargs


def test_resolve_or_create_pod_lifecycle_passes_shipment_uuid_ignores_thread() -> None:
    repo = MagicMock()
    repo.resolve_or_create.return_value = ("lc-pod-1", False)
    svc = WorkflowLifecycleService(lifecycles_repository=repo)
    tenant_uuid = "00000000-0000-4000-8000-0000000000e1"

    with patch(
        "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
        return_value=tenant_uuid,
    ):
        svc.resolve_or_create_lifecycle(
            tenant_id=tenant_uuid,
            workflow_name="pod_lifecycle",
            payload={
                "shipments_row_id": _ROW_UUID,
                "thread_id": "thread-42",
                "shipment_id": "S42",
            },
        )

    repo.resolve_or_create.assert_called_once()
    kwargs = repo.resolve_or_create.call_args.kwargs
    assert kwargs["shipment_id"] == _ROW_UUID
    assert kwargs["thread_id"] is None


def test_shipment_fk_for_lookup_ignores_turvo_number_for_ratecon() -> None:
    assert (
        WorkflowLifecycleService._shipment_fk_for_lookup("ratecon", "SHIP-99")
        is None
    )
    assert (
        WorkflowLifecycleService._shipment_fk_for_lookup("ratecon", _ROW_UUID)
        == _ROW_UUID
    )


def test_insert_lifecycle_sql_omits_email_thread_id() -> None:
    session = MagicMock()
    repo = WorkflowLifecyclesRepository(session)
    repo.insert_lifecycle(
        lifecycle_id="11111111-1111-4111-8111-111111111111",
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        workflow_name="ratecon",
        shipment_id=_ROW_UUID,
    )
    sql = str(session.execute.call_args[0][0])
    assert "email_thread_id" not in sql.lower()


def test_shipment_fk_for_lookup_pass_through_for_load_tendering() -> None:
    assert (
        WorkflowLifecycleService._shipment_fk_for_lookup(
            "load_tendering", "external-ref"
        )
        == "external-ref"
    )
