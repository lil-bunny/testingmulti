"""Tests for ``ActivityLogService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.state import WorkflowState
from app.services.activity_log_service import ActivityLogService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert.return_value = ACTIVITY_UUID
    return repo


def test_record_activity_resolves_slug_and_maps_fields(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=TENANT_UUID,
    ):
        out = svc.record_activity(
            tenant_id="gelita",
            activity_type="workflow_run_started",
            workflow_lifecycle_id=LIFECYCLE_UUID,
            workflow_run_id=RUN_UUID,
            description="started",
            actor_type="system",
            metadata={"event_type": "email_received"},
        )

    assert out == ACTIVITY_UUID
    mock_repo.insert.assert_called_once()
    row = mock_repo.insert.call_args[0][0]
    assert row["tenant_id"] == TENANT_UUID
    assert row["activity_type"] == "workflow_run_started"
    assert row["workflow_lifecycle_id"] == LIFECYCLE_UUID
    assert row["workflow_run_id"] == RUN_UUID
    assert row["description"] == "started"
    assert row["metadata"] == {"event_type": "email_received"}


def test_record_activity_skips_unresolvable_tenant(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=None,
    ):
        out = svc.record_activity(
            tenant_id="unknown",
            activity_type="test",
        )

    assert out is None
    mock_repo.insert.assert_not_called()


def test_record_activity_skips_empty_activity_type(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=TENANT_UUID,
    ):
        out = svc.record_activity(tenant_id=TENANT_UUID, activity_type="  ")

    assert out is None
    mock_repo.insert.assert_not_called()


def test_record_activity_skips_without_lifecycle_and_run(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=TENANT_UUID,
    ):
        out = svc.record_activity(
            tenant_id=TENANT_UUID,
            activity_type="test",
            workflow_run_id="not-a-uuid",
        )

    assert out is None
    mock_repo.insert.assert_not_called()


def test_record_activity_system_actor_defaults_actor_id(mock_repo: MagicMock) -> None:
    from app.services.activity_log_service import SYSTEM_ACTOR_ID

    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=TENANT_UUID,
    ):
        svc.record_activity(
            tenant_id=TENANT_UUID,
            activity_type="test",
            workflow_lifecycle_id=LIFECYCLE_UUID,
            workflow_run_id=RUN_UUID,
            actor_type="system",
        )

    row = mock_repo.insert.call_args[0][0]
    assert row["actor_id"] == SYSTEM_ACTOR_ID


TENDER_UUID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


@patch(
    "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_record_tender_created_action_requires_lifecycle_and_run(
    mock_resolve: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType, ActorType
    from app.models.status import StatusSubType, StatusType

    svc = ActivityLogService(repository=mock_repo)
    svc.record_tender_created_action(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        order_number="ORD-1",
        customer_name="Acme Corp",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )

    row = mock_repo.insert.call_args[0][0]
    assert row["activity_type"] == ActivityType.ACTION.value
    assert row["workflow_lifecycle_id"] == LIFECYCLE_UUID
    assert row["workflow_run_id"] == RUN_UUID
    assert row["from_status"] == StatusType.NONE.value
    assert row["actor_type"] == ActorType.SYSTEM.value
    from app.services.activity_log_service import SYSTEM_ACTOR_ID

    assert row["actor_id"] == SYSTEM_ACTOR_ID


@patch(
    "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_record_tender_processing_status_change_uses_record_activity(
    mock_resolve: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType

    svc = ActivityLogService(repository=mock_repo)
    svc.record_tender_processing_status_change(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )

    mock_repo.insert.assert_called_once()
    row = mock_repo.insert.call_args[0][0]
    assert row["activity_type"] == ActivityType.STATUS_CHANGE.value
    assert row["to_status"] == StatusType.PROCESSING.value
    assert row["to_sub_status"] == StatusSubType.TENDER_CREATED.value


def test_record_from_workflow_state(mock_repo: MagicMock) -> None:
    state = WorkflowState(
        tenant_id="gelita",
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "tenant_id": "gelita",
            "workflow_lifecycle_id": LIFECYCLE_UUID,
        },
    )
    svc = ActivityLogService(repository=mock_repo)
    with patch(
        "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
        return_value=TENANT_UUID,
    ):
        out = svc.record_from_workflow_state(
            state,
            activity_type="load_tendering_context_logged",
            metadata={"load_id": "x:0:ORD-1"},
        )

    assert out == ACTIVITY_UUID
    row = mock_repo.insert.call_args[0][0]
    assert row["workflow_lifecycle_id"] == LIFECYCLE_UUID
    assert row["workflow_run_id"] == RUN_UUID
