"""Tests for ``PodReviewResolveService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.activity_log_write import ActivityLogSequenceResult
from app.domain.api_user import ApiUser
from app.models.activity_type import ActorType
from app.services.pod_tms_upload_service import PodLifecycleNotFoundError
from app.services.pod_review_resolve_service import PodReviewResolveService
from tests.helpers.auth_tokens import make_test_api_user

LIFECYCLE_UUID = "22222222-2222-2222-2222-222222222222"
SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SHIPMENT_NUMBER = "TMS-12345"
ACTIVITY_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@pytest.fixture
def user() -> ApiUser:
    return make_test_api_user()


def test_resolve_records_tms_upload_completion_sequence(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.return_value = MagicMock(
        tenant_uuid="11111111-1111-1111-1111-111111111111",
        shipment_number=SHIPMENT_NUMBER,
        shipments_row_id=SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
    )
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "pod_started",
    }

    with patch(
        "app.services.pod_review_resolve_service.record_pod_tms_upload_activity",
        return_value=ActivityLogSequenceResult(
            activity_log_ids=[ACTIVITY_UUID, "ffffffff-ffff-ffff-ffff-ffffffffffff"],
            lifecycle_updated=True,
        ),
    ) as record_fn:
        result = PodReviewResolveService(
            pod_service=pod,
            lifecycle_service=lifecycle,
        ).resolve(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="Uploaded outside portal",
            user=user,
        )

    assert result.shipment_id == SHIPMENTS_ROW_UUID
    assert result.workflow_lifecycle_id == LIFECYCLE_UUID
    assert result.activity_log_ids == [
        ACTIVITY_UUID,
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]
    assert result.to_status == "completed"
    assert result.to_sub_status == "uploaded_to_tms"

    record_fn.assert_called_once()
    kwargs = record_fn.call_args.kwargs
    assert kwargs["outcome"] == "uploaded"
    assert kwargs["actor_type"] == ActorType.USER
    assert kwargs["actor_id"] == str(user.id)
    assert kwargs["extra_metadata"] == {
        "comment": "Uploaded outside portal",
        "resolved_via": "portal",
    }
    assert kwargs["scope"].workflow_run_id is None


def test_resolve_rejects_blank_comment(user: ApiUser) -> None:
    svc = PodReviewResolveService()
    with pytest.raises(ValueError, match="comment is required"):
        svc.resolve(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="   ",
            user=user,
        )


def test_resolve_raises_when_pod_lifecycle_missing(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.side_effect = PodLifecycleNotFoundError(
        "pod_lifecycle not found for shipment"
    )

    svc = PodReviewResolveService(pod_service=pod)
    with pytest.raises(PodLifecycleNotFoundError):
        svc.resolve(
            tenant_slug="t3ra",
            shipment_id=SHIPMENTS_ROW_UUID,
            comment="Done",
            user=user,
        )


def test_resolve_raises_when_activity_sequence_fails(user: ApiUser) -> None:
    pod = MagicMock()
    pod.resolve_pod_lifecycle.return_value = MagicMock(
        tenant_uuid="11111111-1111-1111-1111-111111111111",
        shipment_number=SHIPMENT_NUMBER,
        shipments_row_id=SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
    )
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "pod_started",
    }

    with patch(
        "app.services.pod_review_resolve_service.record_pod_tms_upload_activity",
        return_value=None,
    ):
        svc = PodReviewResolveService(
            pod_service=pod,
            lifecycle_service=lifecycle,
        )
        with pytest.raises(RuntimeError, match="failed to record"):
            svc.resolve(
                tenant_slug="t3ra",
                shipment_id=SHIPMENTS_ROW_UUID,
                comment="Done",
                user=user,
            )
