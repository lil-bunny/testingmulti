"""Thread resolution via communications linked to workflow runs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.communications.service import CommunicationsService

_TENANT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_resolve_thread_for_lifecycle_delegates_to_repository() -> None:
    repo = MagicMock()
    repo.find_inbound_thread_for_lifecycle.return_value = "  thread-from-comm  "
    svc = CommunicationsService(repository=repo)

    thread = svc.resolve_thread_for_lifecycle(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
    )

    assert thread == "thread-from-comm"
    repo.find_inbound_thread_for_lifecycle.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
    )


def test_resolve_thread_for_lifecycle_returns_none_when_unlinked() -> None:
    repo = MagicMock()
    repo.find_inbound_thread_for_lifecycle.return_value = None
    svc = CommunicationsService(repository=repo)

    assert (
        svc.resolve_thread_for_lifecycle(
            tenant_id=_TENANT_UUID,
            workflow_lifecycle_id=_LIFECYCLE_UUID,
        )
        is None
    )


def test_link_inbound_to_workflow_run_delegates_to_repository() -> None:
    repo = MagicMock()
    repo.link_workflow_run.return_value = True
    svc = CommunicationsService(repository=repo)

    linked = svc.link_inbound_to_workflow_run(
        communication_id="11111111-2222-3333-4444-555555555555",
        workflow_run_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
    )

    assert linked is True
    repo.link_workflow_run.assert_called_once()
