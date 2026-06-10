"""Tests for ``ActivityLogService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogStep,
    ActivityLogWrite,
)
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
TENDER_UUID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert.return_value = ACTIVITY_UUID
    return repo


def _write(**kwargs) -> ActivityLogWrite:
    base = dict(
        tenant_id=TENANT_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )
    base.update(kwargs)
    return ActivityLogWrite(**base)


def test_record_activity_legacy_string_type_uses_repo(mock_repo: MagicMock) -> None:
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


@patch("app.services.activity_log_service.LifecycleTransitionService")
def test_record_action_delegates_without_direct_insert(
    mock_transition_cls: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionResult

    mock_transition = MagicMock()
    mock_transition.apply.return_value = LifecycleTransitionResult(
        lifecycle_updated=False,
        activity_log_id=ACTIVITY_UUID,
        from_status=StatusType.PROCESSING,
        from_sub_status=StatusSubType.TENDER_CREATED,
        to_status=StatusType.PROCESSING,
        to_sub_status=StatusSubType.TENDER_CREATED,
    )
    mock_transition_cls.return_value = mock_transition

    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_action(_write(description="side effect"))

    assert out == ACTIVITY_UUID
    mock_transition.apply.assert_called_once()
    command = mock_transition.apply.call_args[0][0]
    assert command.activity_type == ActivityType.ACTION
    assert command.update_lifecycle is False
    mock_repo.insert.assert_not_called()


@patch("app.services.activity_log_service.LifecycleTransitionService")
def test_record_status_change_delegates(
    mock_transition_cls: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionResult

    mock_transition = MagicMock()
    mock_transition.apply.return_value = LifecycleTransitionResult(
        lifecycle_updated=True,
        activity_log_id=ACTIVITY_UUID,
        from_status=StatusType.NONE,
        from_sub_status=StatusSubType.NONE,
        to_status=StatusType.PROCESSING,
        to_sub_status=StatusSubType.TENDER_CREATED,
    )
    mock_transition_cls.return_value = mock_transition

    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_status_change(
        _write(
            description="Status updated to Processing",
            to_status=StatusType.PROCESSING,
            to_sub_status=StatusSubType.TENDER_CREATED,
            from_status=StatusType.NONE,
            from_sub_status=StatusSubType.NONE,
            metadata={"tender_id": TENDER_UUID},
        )
    )

    assert out == ACTIVITY_UUID
    command = mock_transition.apply.call_args[0][0]
    assert command.activity_type == ActivityType.STATUS_CHANGE
    assert command.to_status == StatusType.PROCESSING


@patch("app.services.activity_log_service.LifecycleTransitionService")
def test_record_sequence_calls_apply_sequence(
    mock_transition_cls: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionSequenceResult

    mock_transition = MagicMock()
    mock_transition.apply_sequence.return_value = LifecycleTransitionSequenceResult(
        activity_log_ids=[ACTIVITY_UUID, "ffffffff-ffff-ffff-ffff-ffffffffffff"],
        lifecycle_updated=True,
    )
    mock_transition_cls.return_value = mock_transition

    svc = ActivityLogService(repository=mock_repo)
    result = svc.record_sequence(
        ActivityLogSequence(
            tenant_id=TENANT_UUID,
            workflow_lifecycle_id=LIFECYCLE_UUID,
            workflow_run_id=RUN_UUID,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description="Tender created",
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PROCESSING,
                    to_sub_status=StatusSubType.TENDER_CREATED,
                ),
            ),
        )
    )

    assert result is not None
    assert len(result.activity_log_ids) == 2
    mock_transition.apply_sequence.assert_called_once()
    commands = mock_transition.apply_sequence.call_args[0]
    assert len(commands) == 2
    assert commands[0].activity_type == ActivityType.ACTION
    assert commands[1].activity_type == ActivityType.STATUS_CHANGE


def test_record_activity_skips_without_lifecycle_and_run(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_action(
        _write(workflow_run_id="not-a-uuid", workflow_lifecycle_id=LIFECYCLE_UUID)
    )
    assert out is None


def test_record_action_skips_without_workflow_lifecycle_id(mock_repo: MagicMock) -> None:
    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_action(
        _write(
            workflow_lifecycle_id="",
            workflow_run_id=None,
            description="PoD review acknowledged",
        )
    )
    assert out is None


@patch("app.services.activity_log_service.LifecycleTransitionService")
def test_record_action_portal_lifecycle_scoped_without_run_id(
    mock_transition_cls: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionResult

    mock_transition = MagicMock()
    mock_transition.apply.return_value = LifecycleTransitionResult(
        lifecycle_updated=False,
        activity_log_id=ACTIVITY_UUID,
        from_status=StatusType.PROCESSING,
        from_sub_status=StatusSubType.POD_STARTED,
        to_status=StatusType.PROCESSING,
        to_sub_status=StatusSubType.POD_STARTED,
    )
    mock_transition_cls.return_value = mock_transition

    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_action(
        _write(
            workflow_lifecycle_id=LIFECYCLE_UUID,
            workflow_run_id=None,
            description="PoD review acknowledged",
        )
    )

    assert out == ACTIVITY_UUID
    command = mock_transition.apply.call_args[0][0]
    assert command.workflow_lifecycle_id == LIFECYCLE_UUID
    assert command.workflow_run_id is None
    assert command.update_lifecycle is False


@patch("app.services.activity_log_service.LifecycleTransitionService")
def test_record_sequence_portal_lifecycle_scoped_without_run_id(
    mock_transition_cls: MagicMock,
    mock_repo: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionSequenceResult

    mock_transition = MagicMock()
    mock_transition.apply_sequence.return_value = LifecycleTransitionSequenceResult(
        activity_log_ids=[ACTIVITY_UUID, "ffffffff-ffff-ffff-ffff-ffffffffffff"],
        lifecycle_updated=True,
    )
    mock_transition_cls.return_value = mock_transition

    svc = ActivityLogService(repository=mock_repo)
    result = svc.record_sequence(
        ActivityLogSequence(
            tenant_id=TENANT_UUID,
            workflow_lifecycle_id=LIFECYCLE_UUID,
            workflow_run_id=None,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description="POD document uploaded to TMS",
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.COMPLETED,
                    to_sub_status=StatusSubType.UPLOADED_TO_TMS,
                ),
            ),
        )
    )

    assert result is not None
    mock_transition.apply_sequence.assert_called_once()
    commands = mock_transition.apply_sequence.call_args[0]
    assert commands[0].workflow_run_id is None


def test_record_status_change_skips_without_lifecycle_and_run(
    mock_repo: MagicMock,
) -> None:
    svc = ActivityLogService(repository=mock_repo)
    out = svc.record_status_change(
        _write(
            workflow_lifecycle_id="",
            workflow_run_id=None,
            to_status=StatusType.COMPLETED,
        )
    )
    assert out is None


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
    mock_repo.insert.assert_called_once()
