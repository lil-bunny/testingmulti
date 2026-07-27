"""Unit tests for WorkflowLifecyclesRepository.claim_appointment_draft_send_queued."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.appointment_scheduling.constants import EMAIL_DRAFT, EMAIL_SENT
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository

_TENANT = "11111111-1111-1111-1111-111111111111"
_LIFECYCLE = "22222222-2222-2222-2222-222222222222"


def _ready_draft_meta(**extra):
    return {
        EMAIL_DRAFT: {
            "to": "wh@example.com",
            "subject": "DEL APPT",
            "full_html": "<p>Hi</p>",
        },
        **extra,
    }


def _repo_with_locked_row(*, status: str, sub_status: str, tenant_id: str, metadata) -> WorkflowLifecyclesRepository:
    session = MagicMock()
    lock_result = MagicMock()
    lock_result.first.return_value = (status, sub_status, tenant_id, metadata)

    update_result = MagicMock()
    update_result.rowcount = 1

    def execute(sql, params=None):
        sql_text = str(sql)
        if "FOR UPDATE" in sql_text:
            return lock_result
        return update_result

    session.execute.side_effect = execute
    return WorkflowLifecyclesRepository(session)


def test_claim_wins_when_draft_ready() -> None:
    repo = _repo_with_locked_row(
        status="pending_review",
        sub_status="appointment_draft_created",
        tenant_id=_TENANT,
        metadata=_ready_draft_meta(),
    )
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "claimed"
    )


def test_claim_conflict_when_already_sent() -> None:
    repo = _repo_with_locked_row(
        status="pending_review",
        sub_status="appointment_draft_created",
        tenant_id=_TENANT,
        metadata=_ready_draft_meta(**{EMAIL_SENT: True}),
    )
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "conflict"
    )


def test_claim_conflict_when_awaiting_reply() -> None:
    repo = _repo_with_locked_row(
        status="pending_review",
        sub_status="awaiting_customer_reply",
        tenant_id=_TENANT,
        metadata=_ready_draft_meta(),
    )
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "conflict"
    )


def test_claim_not_found_wrong_tenant() -> None:
    repo = _repo_with_locked_row(
        status="pending_review",
        sub_status="appointment_draft_created",
        tenant_id="00000000-0000-0000-0000-000000000000",
        metadata=_ready_draft_meta(),
    )
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "not_found"
    )


def test_claim_missing_email_draft() -> None:
    repo = _repo_with_locked_row(
        status="pending_review",
        sub_status="appointment_draft_created",
        tenant_id=_TENANT,
        metadata={},
    )
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "scheduling_draft_not_ready"
    )


def test_claim_not_found_when_missing_row() -> None:
    session = MagicMock()
    lock_result = MagicMock()
    lock_result.first.return_value = None
    session.execute.return_value = lock_result
    repo = WorkflowLifecyclesRepository(session)
    assert (
        repo.claim_appointment_draft_send_queued(
            lifecycle_id=_LIFECYCLE,
            expected_tenant_id=_TENANT,
        )
        == "not_found"
    )
