"""Unit tests for WorkflowReviewService (generic acknowledge / resolve)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.activity_log_constants import (
    WORKFLOW_REVIEW_ACKNOWLEDGED_ACTION,
    WORKFLOW_REVIEW_RESOLVED_ACTION,
)
from app.domain.activity_log_write import ActivityLogSequenceResult
from app.domain.api_user import ApiUser
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.workflow_review_service import (
    WorkflowLifecycleNotFoundError,
    WorkflowReviewService,
)

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_LIFECYCLE_UUID = "22222222-2222-2222-2222-222222222222"
_ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
_USER_ID = "99999999-9999-9999-9999-999999999999"


@pytest.fixture
def user() -> ApiUser:
    return ApiUser(
        id=_USER_ID,
        name="Test User",
        email="test@example.com",
        tenant_id=_TENANT_UUID,
        tenant_ids=[_TENANT_UUID],
        permissions=[],
    )


def _lifecycle_service(row: dict | None) -> MagicMock:
    svc = MagicMock()
    svc.read_lifecycle_row_by_id.return_value = row
    return svc


def _owned_row() -> dict:
    return {
        "id": _LIFECYCLE_UUID,
        "tenant_id": _TENANT_UUID,
        "workflow_name": "load_tendering",
        "status": "pending_review",
        "sub_status": "tender_sent_to_carrier",
    }


def test_acknowledge_records_action_without_status_change(user: ApiUser) -> None:
    activity_logs = MagicMock()
    activity_logs.record_action.return_value = _ACTIVITY_UUID
    svc = WorkflowReviewService(
        lifecycle_service=_lifecycle_service(_owned_row()),
        activity_log_service=activity_logs,
    )

    with patch(
        "app.services.workflow_review_service.get_slug_for_tenant_uuid",
        return_value=_TENANT_SLUG,
    ):
        result = svc.acknowledge(
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            comment="Looks good",
            user=user,
        )

    assert result.workflow_lifecycle_id == _LIFECYCLE_UUID
    assert result.workflow_name == "load_tendering"
    assert result.activity_log_id == _ACTIVITY_UUID

    write = activity_logs.record_action.call_args[0][0]
    assert write.workflow_lifecycle_id == _LIFECYCLE_UUID
    assert write.workflow_run_id is None
    assert write.actor_type == ActorType.USER
    assert write.actor_id == _USER_ID
    assert write.metadata["comment"] == "Looks good"
    assert write.description == WORKFLOW_REVIEW_ACKNOWLEDGED_ACTION


def test_resolve_marks_completed_resolved_manually(user: ApiUser) -> None:
    activity_logs = MagicMock()
    activity_logs.record_sequence.return_value = ActivityLogSequenceResult(
        activity_log_ids=[_ACTIVITY_UUID, "ffffffff-ffff-ffff-ffff-ffffffffffff"],
        lifecycle_updated=True,
    )
    svc = WorkflowReviewService(
        lifecycle_service=_lifecycle_service(_owned_row()),
        activity_log_service=activity_logs,
    )

    with patch(
        "app.services.workflow_review_service.get_slug_for_tenant_uuid",
        return_value=_TENANT_SLUG,
    ):
        result = svc.resolve(
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            comment="Handled in TMS directly",
            user=user,
        )

    assert result.to_status == StatusType.COMPLETED.value
    assert result.to_sub_status == StatusSubType.RESOLVED_MANUALLY.value
    assert len(result.activity_log_ids) == 2

    sequence = activity_logs.record_sequence.call_args[0][0]
    assert sequence.actor_type == ActorType.USER
    assert sequence.actor_id == _USER_ID
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == WORKFLOW_REVIEW_RESOLVED_ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.RESOLVED_MANUALLY
    assert sequence.steps[0].metadata["comment"] == "Handled in TMS directly"
    assert sequence.steps[0].metadata["resolved_via"] == "portal"


def test_acknowledge_blank_comment_raises(user: ApiUser) -> None:
    svc = WorkflowReviewService(
        lifecycle_service=_lifecycle_service(_owned_row()),
        activity_log_service=MagicMock(),
    )
    with pytest.raises(ValueError, match="comment is required"):
        svc.acknowledge(
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            comment="   ",
            user=user,
        )


def test_acknowledge_invalid_lifecycle_uuid_raises_422(user: ApiUser) -> None:
    lifecycle = _lifecycle_service(_owned_row())
    svc = WorkflowReviewService(
        lifecycle_service=lifecycle,
        activity_log_service=MagicMock(),
    )
    with pytest.raises(ValueError, match="invalid workflow_lifecycle_id"):
        svc.acknowledge(
            workflow_lifecycle_id="$b6175ca1-da8d-4397-b935-212ed07a1ca3",
            comment="Looks good",
            user=user,
        )
    lifecycle.read_lifecycle_row_by_id.assert_not_called()


def test_resolve_invalid_lifecycle_uuid_raises_422(user: ApiUser) -> None:
    lifecycle = _lifecycle_service(_owned_row())
    activity_logs = MagicMock()
    svc = WorkflowReviewService(
        lifecycle_service=lifecycle,
        activity_log_service=activity_logs,
    )
    with pytest.raises(ValueError, match="invalid workflow_lifecycle_id"):
        svc.resolve(
            workflow_lifecycle_id="not-a-uuid",
            comment="Handled manually",
            user=user,
        )
    lifecycle.read_lifecycle_row_by_id.assert_not_called()
    activity_logs.record_sequence.assert_not_called()


def test_acknowledge_missing_lifecycle_raises_not_found(user: ApiUser) -> None:
    svc = WorkflowReviewService(
        lifecycle_service=_lifecycle_service(None),
        activity_log_service=MagicMock(),
    )
    with patch(
        "app.services.workflow_review_service.get_slug_for_tenant_uuid",
        return_value=_TENANT_SLUG,
    ):
        with pytest.raises(WorkflowLifecycleNotFoundError):
            svc.acknowledge(
                workflow_lifecycle_id=_LIFECYCLE_UUID,
                comment="Looks good",
                user=user,
            )


def test_resolve_other_tenant_lifecycle_raises_not_found(user: ApiUser) -> None:
    foreign_row = {**_owned_row(), "tenant_id": "00000000-0000-0000-0000-000000000000"}
    activity_logs = MagicMock()
    svc = WorkflowReviewService(
        lifecycle_service=_lifecycle_service(foreign_row),
        activity_log_service=activity_logs,
    )
    with patch(
        "app.services.workflow_review_service.get_slug_for_tenant_uuid",
        return_value=_TENANT_SLUG,
    ):
        with pytest.raises(WorkflowLifecycleNotFoundError):
            svc.resolve(
                workflow_lifecycle_id=_LIFECYCLE_UUID,
                comment="Handled manually",
                user=user,
            )
    activity_logs.record_sequence.assert_not_called()
