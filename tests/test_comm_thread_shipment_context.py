"""Tests for thread → shipment context via communications."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.communications.service import CommunicationsService

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_THREAD_ID = "thread-shipment-context-1"


def test_find_shipment_context_for_thread_delegates_to_repository() -> None:
    repo = MagicMock()
    repo.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "lc-pod-1",
            "workflow_name": "pod_lifecycle",
            "shipments_row_id": "ship-row-1",
            "shipment_number": "1000324895",
        }
    ]
    svc = CommunicationsService(repository=repo)

    rows = svc.find_shipment_context_for_thread(
        tenant_id=_TENANT_UUID,
        thread_id=_THREAD_ID,
    )

    assert len(rows) == 1
    assert rows[0]["workflow_name"] == "pod_lifecycle"
    repo.find_shipment_context_for_thread.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        thread_id=_THREAD_ID,
    )


def test_find_shipment_context_for_thread_returns_empty_when_unlinked() -> None:
    repo = MagicMock()
    repo.find_shipment_context_for_thread.return_value = []
    svc = CommunicationsService(repository=repo)

    assert (
        svc.find_shipment_context_for_thread(
            tenant_id=_TENANT_UUID,
            thread_id=_THREAD_ID,
        )
        == []
    )
