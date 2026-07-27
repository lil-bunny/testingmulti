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
from app.models.pause_type import PauseType
from app.models.status import StatusSubType, StatusType
from app.repositories.workflow_lifecycles_repository import LifecycleUpdate
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
    lifecycles.update_lifecycle.return_value = True

    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(_command())

    lifecycles.get_for_update.assert_called_once_with(lifecycle_id=LIFECYCLE_UUID)
    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.COMPLETED,
            sub_status=StatusSubType.ACCEPTED,
            clear_pause=True,
        ),
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
def test_apply_sub_status_change_auto_resumes_from_pending_review(
    _resolve_tenant: MagicMock,
) -> None:
    """A non-exception sub_status_change off ``pending_review`` lifts status to
    ``processing`` and clears any prior ``pause_type`` (forward-progress fix)."""
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.TENDER_CREATED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    lifecycles.update_lifecycle.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_status=None,
            to_sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
        )
    )

    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.PROCESSING,
            sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
            clear_pause=True,
        ),
    )
    row = activity_logs.insert.call_args[0][0]
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PROCESSING.value
    assert row["to_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER.value
    assert result.to_status == StatusType.PROCESSING


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sub_status_change_keeps_pending_review_when_to_status_explicit(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "driver_assignment",
    }
    lifecycles.update_lifecycle.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_status=StatusType.PENDING_REVIEW,
            to_sub_status=StatusSubType.REMINDER_2_SENT,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
        )
    )

    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.PENDING_REVIEW,
            sub_status=StatusSubType.REMINDER_2_SENT,
            clear_pause=True,
        ),
    )
    row = activity_logs.insert.call_args[0][0]
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_sub_status"] == StatusSubType.REMINDER_2_SENT.value
    assert result.to_status == StatusType.PENDING_REVIEW


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sub_status_change_keeps_pending_review_for_pod_reminder_ladder(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "pod_lifecycle",
    }
    lifecycles.update_lifecycle.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_status=StatusType.PENDING_REVIEW,
            to_sub_status=StatusSubType.REMINDER_2_SENT,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
        )
    )

    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.PENDING_REVIEW,
            sub_status=StatusSubType.REMINDER_2_SENT,
            clear_pause=True,
        ),
    )
    row = activity_logs.insert.call_args[0][0]
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_sub_status"] == StatusSubType.REMINDER_2_SENT.value
    assert result.to_status == StatusType.PENDING_REVIEW


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_status_change_pod_upload_pending_review_to_processing(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "pod_lifecycle",
    }
    lifecycles.update_lifecycle.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply(
        _command(
            to_status=StatusType.PROCESSING,
            to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
            from_sub_status=StatusSubType.REMINDER_1_SENT,
            activity_type=ActivityType.STATUS_CHANGE,
            description=None,
        )
    )

    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.PROCESSING,
            sub_status=StatusSubType.DOCUMENT_UPLOADED,
            clear_pause=True,
        ),
    )
    row = activity_logs.insert.call_args[0][0]
    assert row["description"] == "Status changed from Pending Review to Processing"
    assert row["from_status"] == StatusType.PENDING_REVIEW.value
    assert row["to_status"] == StatusType.PROCESSING.value
    assert row["from_sub_status"] == StatusSubType.REMINDER_1_SENT.value
    assert row["to_sub_status"] == StatusSubType.DOCUMENT_UPLOADED.value
    assert result.to_status == StatusType.PROCESSING
    assert result.to_sub_status == StatusSubType.DOCUMENT_UPLOADED


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_apply_sequence_tms_success_sub_bumps_stay_processing(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "driver_assignment",
    }
    lifecycles.update_lifecycle.return_value = True
    activity_logs = MagicMock()
    activity_logs.insert.side_effect = ["reminder-log-id", "uploaded-log-id"]

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    result = svc.apply_sequence(
        _command(
            to_status=StatusType.PROCESSING,
            to_sub_status=StatusSubType.REMINDER_3_SENT,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            description=None,
        ),
        _command(
            to_status=StatusType.PROCESSING,
            to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            description=None,
        ),
    )

    assert result.lifecycle_updated is True
    assert lifecycles.update_lifecycle.call_count == 2
    for call in lifecycles.update_lifecycle.call_args_list:
        assert call.kwargs["update"].status == StatusType.PROCESSING
    reminder_row = activity_logs.insert.call_args_list[0][0][0]
    uploaded_row = activity_logs.insert.call_args_list[1][0][0]
    assert reminder_row["from_status"] == StatusType.PROCESSING.value
    assert reminder_row["to_status"] == StatusType.PROCESSING.value
    assert reminder_row["to_sub_status"] == StatusSubType.REMINDER_3_SENT.value
    assert uploaded_row["from_status"] == StatusType.PROCESSING.value
    assert uploaded_row["to_status"] == StatusType.PROCESSING.value
    assert uploaded_row["to_sub_status"] == StatusSubType.UPLOADED_TO_TMS.value


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
    lifecycles.update_lifecycle.return_value = True
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

    lifecycles.update_lifecycle.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        update=LifecycleUpdate(
            status=StatusType.COMPLETED,
            sub_status=StatusSubType.DO_NOTHING,
            clear_pause=True,
        ),
    )
    activity_logs.insert.assert_not_called()
    assert result.lifecycle_updated is True
    assert result.activity_log_id is None


@patch(
    "app.services.lifecycle_transition_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
@pytest.mark.parametrize(
    ("activity_type", "status", "sub_status", "description"),
    [
        (
            ActivityType.ACTION,
            StatusType.PENDING_REVIEW,
            StatusSubType.TENDER_SENT_TO_CARRIER,
            "Queued reminders",
        ),
        (
            ActivityType.EXCEPTION,
            StatusType.PROCESSING,
            StatusSubType.TENDER_CREATED,
            "Product pack code is required.",
        ),
    ],
)
def test_apply_snapshot_activity_type_without_lifecycle_update(
    _resolve_tenant: MagicMock,
    activity_type: ActivityType,
    status: StatusType,
    sub_status: StatusSubType,
    description: str,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": status.value,
        "sub_status": sub_status.value,
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
            activity_type=activity_type,
            to_status=StatusType.COMPLETED,
            to_sub_status=StatusSubType.ACCEPTED,
            update_lifecycle=True,
            description=description,
            metadata={"error": "missing_pack_code"}
            if activity_type == ActivityType.EXCEPTION
            else None,
        )
    )

    if activity_type is ActivityType.EXCEPTION:
        lifecycles.update_lifecycle.assert_called_once_with(
            lifecycle_id=LIFECYCLE_UUID,
            update=LifecycleUpdate(pause_type=PauseType.SYSTEM_ERROR),
        )
    else:
        lifecycles.update_lifecycle.assert_not_called()
    row = activity_logs.insert.call_args[0][0]
    assert row["activity_type"] == activity_type.value
    assert row["from_status"] == status.value
    assert row["to_status"] == status.value
    assert row["from_sub_status"] == sub_status.value
    assert row["to_sub_status"] == sub_status.value
    assert result.lifecycle_updated is False
    assert result.from_status == status
    assert result.to_status == status


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
    lifecycles.update_lifecycle.assert_not_called()
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
    lifecycles.update_lifecycle.return_value = True
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

    lifecycles.update_lifecycle.assert_called_once()
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
    lifecycles.update_lifecycle.return_value = True
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

    lifecycles.update_lifecycle.assert_called_once()


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
    lifecycles.update_lifecycle.return_value = True
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
def test_apply_from_state_explicit_none_skips_state_communication_id(
    _resolve_tenant: MagicMock,
) -> None:
    lifecycles = MagicMock()
    lifecycles.get_for_update.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_CREATED.value,
        "tenant_id": TENANT_UUID,
        "workflow_name": "load_tendering",
    }
    activity_logs = MagicMock()
    activity_logs.insert.return_value = ACTIVITY_UUID

    state = WorkflowState(
        tenant_id="gelita",
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "communication_id": COMM_UUID,
        },
    )

    svc = LifecycleTransitionService(
        lifecycles_repo=lifecycles,
        activity_logs_repo=activity_logs,
    )
    svc.apply_from_state(
        state,
        activity_type=ActivityType.ACTION,
        description="Turvo delivery placeholder set",
        update_lifecycle=False,
        communication_id=None,
    )

    row = activity_logs.insert.call_args[0][0]
    assert row["communication_id"] is None


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
    lifecycles.update_lifecycle.return_value = True
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
