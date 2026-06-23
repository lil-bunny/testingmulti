"""Tests for ``LifecycleTransitionService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
)
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMM_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


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
def test_apply_updates_lifecycle_and_inserts_activity(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True

    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(_command())

    lifecycles.get_for_update.assert_called_once_with(lifecycle_id=LIFECYCLE_UUID)
    lifecycles.update_status.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.ACCEPTED,
    )
    activity_logs.insert.assert_called_once()
    row = activity_logs.insert.call_args[0][0]
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
def test_apply_sub_status_only_keeps_top_level_status_on_log(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_TENANT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

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
        lifecycle_id=LIFECYCLE_UUID,
        status=None,
        sub_status=StatusSubType.ESCALATED,
    )
    row = activity_logs.insert.call_args[0][0]
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_sub_status"] == StatusSubType.ESCALATED.value
    assert (
        row["description"]
        == "Sub-status changed from Tender Sent To Tenant to Escalated"
    )
    assert result.to_status == StatusType.PENDING_REVIEW


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_lifecycle_only_when_record_activity_false(
    _resolve_tenant: MagicMock,
) -> None:
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
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.DO_NOTHING,
    )
    activity_logs.insert.assert_not_called()
    assert result.lifecycle_updated is True
    assert result.activity_log_id is None


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_action_snapshots_lifecycle_without_update(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

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
    row = activity_logs.insert.call_args[0][0]
    assert row["activity_type"] == ActivityType.ACTION.value
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["from_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER.value
    assert row["to_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER.value
    assert result.lifecycle_updated is False
    assert result.from_status == StatusType.PENDING_REVIEW
    assert result.to_status == StatusType.PENDING_REVIEW


def test_apply_requires_workflow_lifecycle_id() -> None:
    svc = LifecycleTransitionService(
        lifecycles_repo=MagicMock(),
        activity_logs_repo=MagicMock(),
    )
    with pytest.raises(LifecycleTransitionError, match="workflow_lifecycle_id is required"):
        svc.apply(
            _command(
                activity_type=ActivityType.ACTION,
                workflow_lifecycle_id="",
                workflow_run_id=None,
                description="PoD review acknowledged",
                update_lifecycle=False,
            )
        )


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_portal_lifecycle_scoped_action_without_run_id(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "pod_lifecycle",
    }
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            activity_type=ActivityType.ACTION,
            workflow_run_id=None,
            description="PoD review acknowledged",
            update_lifecycle=False,
            actor_type=ActorType.USER,
            actor_id="99999999-9999-9999-9999-999999999999",
        )
    )

    lifecycles.get_for_update.assert_called_once_with(lifecycle_id=LIFECYCLE_UUID)
    lifecycles.update_status.assert_not_called()
    row = activity_logs.insert.call_args[0][0]
    assert row["workflow_lifecycle_id"] == LIFECYCLE_UUID
    assert row["workflow_run_id"] is None
    assert row["from_status"] == StatusType.PROCESSING.value
    assert row["to_status"] == StatusType.PROCESSING.value
    assert row["from_sub_status"] == StatusSubType.POD_STARTED.value
    assert row["to_sub_status"] == StatusSubType.POD_STARTED.value
    assert result.activity_log_id == ACTIVITY_UUID
    assert result.lifecycle_updated is False


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sequence_portal_lifecycle_scoped_without_run_id(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "pod_lifecycle",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.side_effect = [
        ACTIVITY_UUID,
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    action = _command(
        activity_type=ActivityType.ACTION,
        workflow_run_id=None,
        description="POD document uploaded to TMS",
        update_lifecycle=False,
        actor_type=ActorType.USER,
        actor_id="99999999-9999-9999-9999-999999999999",
    )
    status_change = _command(
        activity_type=ActivityType.STATUS_CHANGE,
        workflow_run_id=None,
        to_status=StatusType.COMPLETED,
        to_sub_status=StatusSubType.UPLOADED_TO_TMS,
        actor_type=ActorType.USER,
        actor_id="99999999-9999-9999-9999-999999999999",
    )

    result = svc.apply_sequence(action, status_change)

    lifecycles.update_status.assert_called_once()
    assert activity_logs.insert.call_count == 2
    assert result.activity_log_ids == [
        ACTIVITY_UUID,
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]
    first_row = activity_logs.insert.call_args_list[0][0][0]
    assert first_row["workflow_run_id"] is None


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_action_passes_communication_id_to_insert(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    svc.apply(
        _command(
            activity_type=ActivityType.ACTION,
            update_lifecycle=False,
            description="Tender email sent",
            communication_id=COMM_UUID,
        )
    )

    row = activity_logs.insert.call_args[0][0]
    assert row["communication_id"] == COMM_UUID


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_action_null_lifecycle_status_uses_none(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": None,
        "sub_status": None,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

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

    row = activity_logs.insert.call_args[0][0]
    assert row["from_status"] == StatusType.NONE.value
    assert row["to_status"] == StatusType.NONE.value
    assert row["from_sub_status"] == StatusSubType.NONE.value
    assert row["to_sub_status"] == StatusSubType.NONE.value


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=None,
)
def test_apply_raises_when_tenant_unresolvable(_resolve: MagicMock) -> None:
    lifecycle_transition_service = LifecycleTransitionService(
        lifecycles_repo=MagicMock(),
        activity_logs_repo=MagicMock(),
    )
    with pytest.raises(LifecycleTransitionError):
        lifecycle_transition_service.apply(_command(tenant_id="unknown"))


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_raises_when_lifecycle_missing(
    _resolve: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = None

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=MagicMock(),
    )
    with pytest.raises(LifecycleTransitionError):
        svc.apply(_command())


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sequence_action_then_status_in_one_transaction(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.side_effect = [
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
        ),
    )

    assert result.activity_log_ids == ["action-log-id", "status-log-id"]
    assert result.lifecycle_updated is True
    assert activity_logs.insert.call_count == 2
    lifecycles.get_for_update.assert_called_once()

    action_row = activity_logs.insert.call_args_list[0][0][0]
    status_row = activity_logs.insert.call_args_list[1][0][0]
    assert action_row["activity_type"] == ActivityType.ACTION.value
    assert action_row["from_status"] == StatusType.NONE.value
    assert action_row["to_status"] == StatusType.NONE.value
    assert status_row["activity_type"] == ActivityType.STATUS_CHANGE.value
    assert status_row["from_status"] == StatusType.NONE.value
    assert status_row["to_status"] == StatusType.PROCESSING.value
    assert status_row["to_sub_status"] == StatusSubType.TENDER_CREATED.value
    assert (
        status_row["description"]
        == "Status changed from None to Processing"
    )

    lifecycles.update_status.assert_called_once()


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sequence_tendered_cancel_processing_to_completed(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "driver_assignment",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.side_effect = ["action-log-id", "status-log-id"]

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply_sequence(
        _command(
            activity_type=ActivityType.ACTION,
            description="Driver assignment cancelled — shipment tendered in Turvo",
            workflow_run_id=None,
            update_lifecycle=False,
            to_status=None,
            to_sub_status=None,
        ),
        _command(
            activity_type=ActivityType.STATUS_CHANGE,
            workflow_run_id=None,
            to_status=StatusType.COMPLETED,
            to_sub_status=StatusSubType.CANCELLED,
            description=None,
        ),
    )

    assert result.lifecycle_updated is True
    status_row = activity_logs.insert.call_args_list[1][0][0]
    assert status_row["from_status"] == StatusType.PROCESSING.value
    assert status_row["to_status"] == StatusType.COMPLETED.value
    assert status_row["from_sub_status"] == StatusSubType.REMINDER_1_SENT.value
    assert status_row["to_sub_status"] == StatusSubType.CANCELLED.value
    assert status_row["description"] == "Status changed from Processing to Completed"
    lifecycles.update_status.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.COMPLETED,
        sub_status=StatusSubType.CANCELLED,
    )


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_from_state_passes_communication_id_to_insert(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_CREATED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    state = WorkflowState(
        tenant_id="gelita",
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "communication_id": COMM_UUID,
            "thread_id": "provider-thread-1",
        },
    )

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    svc.apply_from_state(
        state,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        to_sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
    )

    row = activity_logs.insert.call_args[0][0]
    assert row["communication_id"] == COMM_UUID
    assert row["metadata"] == {}


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_status_change_uses_generated_description(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_status.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    svc.apply(
        _command(
            description="ignored custom text",
            to_status=StatusType.COMPLETED,
            to_sub_status=StatusSubType.ACCEPTED,
        )
    )

    row = activity_logs.insert.call_args[0][0]
    assert row["description"] == "Status changed from Processing to Completed"
