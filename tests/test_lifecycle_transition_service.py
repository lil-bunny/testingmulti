"""Tests for ``LifecycleTransitionService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
)
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _command(**overrides) -> LifecycleTransitionCommand:
    base = dict(
        tenant_id="gelita",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=StatusType.COMPLETED,
        to_sub_status=StatusSubType.ACCEPTED,
        description="done",
        actor_type=ActorType.SYSTEM,
    )
    base.update(overrides)
    return LifecycleTransitionCommand(**base)


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_updates_lifecycle_and_inserts_activity(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True

    activity_logs = MagicMock()
    activity_logs.insert_with_connection.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(_command())

    lifecycles.get_for_update.assert_called_once_with(
        conn, lifecycle_id=LIFECYCLE_UUID
    )
    lifecycles.update_status.assert_called_once_with(
        conn,
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.ACCEPTED,
    )
    activity_logs.insert_with_connection.assert_called_once()
    row = activity_logs.insert_with_connection.call_args[0][1]
    assert row["tenant_id"] == TENANT_UUID
    assert row["from_status"] == StatusType.PROCESSING.value
    assert row["to_status"] == StatusType.COMPLETED.value
    assert row["activity_type"] == ActivityType.STATUS_CHANGE.value
    assert result.activity_log_id == ACTIVITY_UUID
    assert result.lifecycle_updated is True


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_sub_status_only_keeps_top_level_status_on_log(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_TENANT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert_with_connection.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_status=None,
            to_sub_status=StatusSubType.ESCALATED,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
        )
    )

    lifecycles.update_status.assert_called_once_with(
        conn,
        lifecycle_id=LIFECYCLE_UUID,
        status=None,
        sub_status=StatusSubType.ESCALATED,
    )
    row = activity_logs.insert_with_connection.call_args[0][1]
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_sub_status"] == StatusSubType.ESCALATED.value
    assert result.to_status == StatusType.PENDING_REVIEW


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_lifecycle_only_when_record_activity_false(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_sub_status=StatusSubType.DO_NOTHING,
            record_activity=False,
        )
    )

    lifecycles.update_status.assert_called_once_with(
        conn,
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.DO_NOTHING,
    )
    activity_logs.insert_with_connection.assert_not_called()
    assert result.lifecycle_updated is True
    assert result.activity_log_id is None


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_action_snapshots_lifecycle_without_update(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert_with_connection.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            activity_type=ActivityType.ACTION,
            to_status=StatusType.COMPLETED,
            to_sub_status=StatusSubType.ACCEPTED,
            update_lifecycle=True,
            description="Queued reminders",
        )
    )

    lifecycles.update_status.assert_not_called()
    row = activity_logs.insert_with_connection.call_args[0][1]
    assert row["activity_type"] == ActivityType.ACTION.value
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["from_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER.value
    assert row["to_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER.value
    assert result.lifecycle_updated is False
    assert result.from_status == StatusType.PENDING_REVIEW
    assert result.to_status == StatusType.PENDING_REVIEW


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_action_null_lifecycle_status_uses_none(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": None,
        "sub_status": None,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert_with_connection.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    svc.apply(
        _command(
            activity_type=ActivityType.ACTION,
            update_lifecycle=False,
            description="Tender created",
        )
    )

    row = activity_logs.insert_with_connection.call_args[0][1]
    assert row["from_status"] == StatusType.NONE.value
    assert row["to_status"] == StatusType.NONE.value
    assert row["from_sub_status"] == StatusSubType.NONE.value
    assert row["to_sub_status"] == StatusSubType.NONE.value


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=None,
)
def test_apply_raises_when_tenant_unresolvable(_resolve: MagicMock) -> None:
    lifecycle_transition_service = LifecycleTransitionService()
    with pytest.raises(LifecycleTransitionError):
        lifecycle_transition_service.apply(_command(tenant_id="unknown"))


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_raises_when_lifecycle_missing(
    mock_uow: MagicMock,
    _resolve: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = None

    svc = LifecycleTransitionService(lifecycles_repo=lifecycles)
    with pytest.raises(LifecycleTransitionError):
        svc.apply(_command())


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@patch("app.services.lifecycle_transition_service.unit_of_work")
def test_apply_sequence_action_then_status_in_one_transaction(
    mock_uow: MagicMock,
    _resolve_tenant: MagicMock,
) -> None:
    conn = MagicMock()
    mock_uow.return_value.__enter__.return_value = conn

    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert_with_connection.side_effect = [
        "action-log-id",
        "status-log-id",
    ]

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply_sequence(
        _command(
            activity_type=ActivityType.ACTION,
            description="Tender created",
            update_lifecycle=False,
        ),
        _command(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=StatusType.PROCESSING,
            to_sub_status=StatusSubType.TENDER_CREATED,
            description="Status updated to Processing",
        ),
    )

    assert result.activity_log_ids == ["action-log-id", "status-log-id"]
    assert result.lifecycle_updated is True
    assert activity_logs.insert_with_connection.call_count == 2
    mock_uow.return_value.__enter__.assert_called_once()

    action_row = activity_logs.insert_with_connection.call_args_list[0][0][1]
    status_row = activity_logs.insert_with_connection.call_args_list[1][0][1]
    assert action_row["activity_type"] == ActivityType.ACTION.value
    assert action_row["from_status"] == StatusType.NONE.value
    assert action_row["to_status"] == StatusType.NONE.value
    assert status_row["activity_type"] == ActivityType.STATUS_CHANGE.value
    assert status_row["from_status"] == StatusType.NONE.value
    assert status_row["to_status"] == StatusType.PROCESSING.value
    assert status_row["to_sub_status"] == StatusSubType.TENDER_CREATED.value

    lifecycles.update_status.assert_called_once()
