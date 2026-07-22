"""Tests for appointment_scheduling duplicate-lifecycle blocking query."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository

_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"


def _repo_with_session() -> tuple[WorkflowLifecyclesRepository, MagicMock]:
    session = MagicMock()
    repo = WorkflowLifecyclesRepository(session)
    return repo, session


def test_find_blocking_excludes_intake_failure_pending_review() -> None:
    repo, session = _repo_with_session()
    session.execute.return_value.first.return_value = None

    found = repo.find_blocking_appointment_scheduling_lifecycle_id(
        tenant_id=_TENANT_UUID,
        workflow_name="appointment_scheduling",
        shipment_number="12345",
    )

    assert found is None
    sql = str(session.execute.call_args[0][0])
    assert "scheduling_failure_reason" in sql
    assert "pending_review" in sql


def test_find_blocking_returns_id_for_draft_pending_review() -> None:
    repo, session = _repo_with_session()
    session.execute.return_value.first.return_value = (_LIFECYCLE_UUID,)

    found = repo.find_blocking_appointment_scheduling_lifecycle_id(
        tenant_id=_TENANT_UUID,
        workflow_name="appointment_scheduling",
        shipment_number="12345",
    )

    assert found == _LIFECYCLE_UUID
