"""Unit tests for Gelita comms ↔ lifecycle correlation SQL (no DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.workflow_run_event_type import WorkflowRunEventType
from app.repositories.communications_repository import CommunicationsRepository


def test_find_inbound_thread_for_lifecycle_passes_anchor_event_type() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value="thread-1",
    ) as scalar:
        out = repo.find_inbound_thread_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
            anchor_event_type=WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
        )
    assert out == "thread-1"
    params = scalar.call_args[0][2]
    assert params["anchor_event_type"] == WorkflowRunEventType.CARRIER_EMAIL_RECEIVED


def test_resolve_lifecycle_id_for_thread_returns_earliest_lifecycle() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value="11111111-1111-1111-1111-111111111111",
    ) as scalar:
        out = repo.resolve_lifecycle_id_for_thread(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            thread_id="thread-ack",
            workflow_name="load_tendering",
        )
    assert out == "11111111-1111-1111-1111-111111111111"
    sql = scalar.call_args[0][1]
    assert "ORDER BY c.created_at ASC" in sql
    assert scalar.call_args[0][2]["workflow_name"] == "load_tendering"


def test_is_thread_linked_to_lifecycle_delegates_exists_query() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value=True,
    ):
        assert repo.is_thread_linked_to_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            thread_id="thread-1",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
        )


def test_find_linked_thread_for_lifecycle_returns_thread() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value="other-thread",
    ):
        out = repo.find_linked_thread_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
        )
    assert out == "other-thread"


def test_find_inbound_thread_for_lifecycle_with_attempt_filter() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value="thread-2",
    ) as scalar:
        out = repo.find_inbound_thread_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
            anchor_event_type=WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
            routing_guide_attempt=2,
        )
    assert out == "thread-2"
    sql = scalar.call_args[0][1]
    params = scalar.call_args[0][2]
    assert "routing_guide_attempt" in sql
    assert params["routing_guide_attempt"] == 2


def test_find_inbound_thread_for_lifecycle_without_attempt_unchanged() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value="thread-1",
    ) as scalar:
        repo.find_inbound_thread_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
        )
    sql = scalar.call_args[0][1]
    assert "routing_guide_attempt" not in sql


def test_find_inbound_thread_for_lifecycle_falls_back_without_attempt_metadata() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        side_effect=[None, "legacy-thread"],
    ) as scalar:
        out = repo.find_inbound_thread_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
            anchor_event_type=WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
            routing_guide_attempt=1,
        )
    assert out == "legacy-thread"
    assert scalar.call_count == 2
    first_sql = scalar.call_args_list[0][0][1]
    second_sql = scalar.call_args_list[1][0][1]
    assert "routing_guide_attempt" in first_sql
    assert "routing_guide_attempt' IS NULL" in second_sql


def test_patch_communication_metadata_merges_json() -> None:
    session = MagicMock()
    session.execute.return_value.rowcount = 1
    repo = CommunicationsRepository(session)
    assert repo.patch_communication_metadata(
        communication_id="33333333-3333-3333-3333-333333333333",
        metadata_patch={"routing_guide_attempt": 2},
    )
    sql = str(session.execute.call_args[0][0])
    assert "metadata" in sql


def test_thread_attempt_for_lifecycle_infers_ordinal_without_metadata() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value=1,
    ) as scalar:
        out = repo.thread_attempt_for_lifecycle(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            thread_id="legacy-carrier-1-thread",
            workflow_lifecycle_id="11111111-1111-1111-1111-111111111111",
        )
    assert out == 1
    sql = scalar.call_args[0][1]
    assert "ordinal_attempt" in sql
    assert "COALESCE(stamped_attempt, ordinal_attempt)" in sql


def test_link_workflow_run_idempotent_when_already_linked() -> None:
    session = MagicMock()
    repo = CommunicationsRepository(session)
    run_id = "22222222-2222-2222-2222-222222222222"
    comm_id = "33333333-3333-3333-3333-333333333333"
    with patch(
        "app.repositories.communications_repository.execute_scalar",
        return_value=run_id,
    ):
        assert repo.link_workflow_run(
            communication_id=comm_id,
            workflow_run_id=run_id,
        )
    session.execute.assert_not_called()
