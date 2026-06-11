"""Tests for linking ``workflow_lifecycles.shipment_id`` to ``shipments.id``."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.workflow_lifecycle_service import WorkflowLifecycleService

_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LIFECYCLE_ID = "11111111-2222-3333-4444-555555555555"
_TURVO_NUMBER = "1000324895"


def test_extract_db_shipment_id_prefers_shipments_row_id() -> None:
    row_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    payload = {
        "shipment_id": "1000324895",
        "shipments_row_id": row_uuid,
    }
    assert WorkflowLifecycleService._extract_db_shipment_id(payload) == row_uuid


def test_extract_db_shipment_id_ignores_turvo_numeric() -> None:
    assert (
        WorkflowLifecycleService._extract_db_shipment_id(
            {"shipment_id": "1000324895"}
        )
        is None
    )


def test_extract_db_shipment_id_accepts_uuid_in_shipment_id() -> None:
    row_uuid = str(uuid.uuid4())
    assert (
        WorkflowLifecycleService._extract_db_shipment_id(
            {"shipment_id": row_uuid}
        )
        == row_uuid
    )


def test_link_shipment_row_calls_repo() -> None:
    repo = MagicMock()
    repo.update_shipment_id_tx.return_value = True
    svc = WorkflowLifecycleService(lifecycles_repository=repo)
    row_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    ok = svc.link_shipment_row(
        lifecycle_id="11111111-2222-3333-4444-555555555555",
        shipments_row_id=row_uuid,
    )
    assert ok is True
    repo.update_shipment_id_tx.assert_called_once_with(
        lifecycle_id="11111111-2222-3333-4444-555555555555",
        shipment_id=row_uuid,
    )


def test_link_shipment_row_rejects_invalid_uuid() -> None:
    repo = MagicMock()
    svc = WorkflowLifecycleService(lifecycles_repository=repo)
    assert (
        svc.link_shipment_row(
            lifecycle_id=_LIFECYCLE_ID,
            shipments_row_id="1000324895",
        )
        is False
    )
    repo.update_shipment_id_tx.assert_not_called()


def test_resolve_shipments_row_id_from_payload_row_id() -> None:
    repo = MagicMock()
    shipments = MagicMock()
    svc = WorkflowLifecycleService(
        lifecycles_repository=repo,
        shipments_service=shipments,
    )
    assert (
        svc.resolve_shipments_row_id(
            tenant_id="tenant-uuid",
            payload={"shipments_row_id": _ROW_UUID, "shipment_id": _TURVO_NUMBER},
        )
        == _ROW_UUID
    )
    shipments.get_by_shipment_number.assert_not_called()


def test_resolve_shipments_row_id_looks_up_turvo_number() -> None:
    repo = MagicMock()
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {
        "id": _ROW_UUID,
        "shipment_number": _TURVO_NUMBER,
    }
    svc = WorkflowLifecycleService(
        lifecycles_repository=repo,
        shipments_service=shipments,
    )
    with patch(
        "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
        return_value="tenant-uuid",
    ):
        assert (
            svc.resolve_shipments_row_id(
                tenant_id="t3ra",
                payload={"shipment_id": _TURVO_NUMBER},
            )
            == _ROW_UUID
        )
    shipments.get_by_shipment_number.assert_called_once_with(
        tenant_id="tenant-uuid",
        shipment_number=_TURVO_NUMBER,
    )


def test_ensure_lifecycle_shipment_linked_links_and_returns_uuid() -> None:
    repo = MagicMock()
    repo.update_shipment_id_tx.return_value = True
    shipments = MagicMock()
    svc = WorkflowLifecycleService(
        lifecycles_repository=repo,
        shipments_service=shipments,
    )
    out = svc.ensure_lifecycle_shipment_linked(
        lifecycle_id=_LIFECYCLE_ID,
        tenant_id="tenant-uuid",
        payload={"shipments_row_id": _ROW_UUID},
    )
    assert out == _ROW_UUID
    repo.update_shipment_id_tx.assert_called_once_with(
        lifecycle_id=_LIFECYCLE_ID,
        shipment_id=_ROW_UUID,
    )


def test_ensure_lifecycle_shipment_linked_returns_none_when_unresolved() -> None:
    repo = MagicMock()
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = None
    svc = WorkflowLifecycleService(
        lifecycles_repository=repo,
        shipments_service=shipments,
    )
    with patch(
        "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
        return_value="tenant-uuid",
    ):
        assert (
            svc.ensure_lifecycle_shipment_linked(
                lifecycle_id=_LIFECYCLE_ID,
                tenant_id="t3ra",
                payload={"shipment_id": _TURVO_NUMBER},
            )
            is None
        )
    repo.update_shipment_id_tx.assert_not_called()
