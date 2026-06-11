"""Tests for ``PodReviewAcknowledgeService``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.api_user import ApiUser
from app.models.activity_type import ActorType
from app.services.pod_tms_upload_service import PodLifecycleNotFoundError
from app.services.pod_review_acknowledge_service import PodReviewAcknowledgeService
from tests.helpers.auth_tokens import make_test_api_user

LIFECYCLE_UUID = "22222222-2222-2222-2222-222222222222"
SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
SHIPMENT_NUMBER = "TMS-12345"


@pytest.fixture
def user() -> ApiUser:
    return make_test_api_user()


def test_acknowledge_records_portal_lifecycle_scoped_action(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.return_value = MagicMock(
        tenant_uuid="11111111-1111-1111-1111-111111111111",
        shipment_number=SHIPMENT_NUMBER,
        shipments_row_id=SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
    )
    activity_logs = MagicMock()
    activity_logs.record_action.return_value = ACTIVITY_UUID

    svc = PodReviewAcknowledgeService(
        pod_service=pod,
        activity_log_service=activity_logs,
    )

    result = svc.acknowledge(
        tenant_slug="t3ra",
        shipment_id=SHIPMENTS_ROW_UUID,
        comment="Looks good",
        user=user,
    )

    assert result.shipment_id == SHIPMENTS_ROW_UUID
    assert result.workflow_lifecycle_id == LIFECYCLE_UUID
    assert result.activity_log_id == ACTIVITY_UUID
    pod.resolve_pod_lifecycle.assert_called_once_with(
        tenant_slug="t3ra",
        shipment_id=SHIPMENTS_ROW_UUID,
    )
    write = activity_logs.record_action.call_args[0][0]
    assert write.workflow_lifecycle_id == LIFECYCLE_UUID
    assert write.workflow_run_id is None
    assert write.actor_type == ActorType.USER
    assert write.actor_id == str(user.id)
    assert write.metadata == {
        "comment": "Looks good",
        "shipment_id": SHIPMENT_NUMBER,
        "shipments_row_id": SHIPMENTS_ROW_UUID,
        "workflow_lifecycle_id": LIFECYCLE_UUID,
    }


def test_acknowledge_rejects_blank_comment(user: ApiUser) -> None:
    svc = PodReviewAcknowledgeService()
    with pytest.raises(ValueError, match="comment is required"):
        svc.acknowledge(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="   ",
            user=user,
        )


def test_acknowledge_raises_when_pod_lifecycle_missing(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.side_effect = PodLifecycleNotFoundError(
        "pod_lifecycle not found for shipment"
    )

    svc = PodReviewAcknowledgeService(
        pod_service=pod,
        activity_log_service=MagicMock(),
    )

    with pytest.raises(PodLifecycleNotFoundError):
        svc.acknowledge(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="Looks good",
            user=user,
        )


def test_acknowledge_raises_when_activity_log_fails(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.return_value = MagicMock(
        tenant_uuid="11111111-1111-1111-1111-111111111111",
        shipment_number=SHIPMENT_NUMBER,
        shipments_row_id=SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
    )
    activity_logs = MagicMock()
    activity_logs.record_action.return_value = None

    svc = PodReviewAcknowledgeService(
        pod_service=pod,
        activity_log_service=activity_logs,
    )

    with pytest.raises(RuntimeError, match="failed to record"):
        svc.acknowledge(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="Looks good",
            user=user,
        )
