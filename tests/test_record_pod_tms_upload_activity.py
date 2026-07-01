"""Activity log transitions for POD TMS upload."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.pod_tms_upload_activity import (
    PodLifecycleScope,
    record_pod_tms_upload_activity,
)


def _scope(**kwargs) -> PodLifecycleScope:
    defaults = dict(
        tenant_id="11111111-1111-1111-1111-111111111111",
        workflow_lifecycle_id="22222222-2222-2222-2222-222222222222",
        workflow_run_id="33333333-3333-3333-3333-333333333333",
        shipments_row_id="44444444-4444-4444-4444-444444444444",
        from_status=StatusType.PROCESSING,
        from_sub_status=StatusSubType.POD_STARTED,
    )
    defaults.update(kwargs)
    return PodLifecycleScope(**defaults)


def test_record_uploaded_activity_sequence_matches_ratecon_complete_pattern():
    """action + single status_change (completed + uploaded_to_tms), like ratecon processed."""
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    result = record_pod_tms_upload_activity(
        scope=_scope(),
        shipment_id="1000324895",
        outcome="uploaded",
        activity_log_service=svc,
    )

    assert result is not None
    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.UPLOADED_TO_TMS
    assert sequence.steps[1].metadata is None
    assert sequence.steps[0].metadata == {"outcome": "uploaded"}


def test_record_skipped_activity_completes_lifecycle_with_single_status_change():
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(from_sub_status=StatusSubType.REMINDER_1_SENT),
        shipment_id="1000324895",
        outcome="skipped",
        activity_log_service=svc,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.UPLOADED_TO_TMS


def test_record_skipped_when_already_completed_only_sub_status_change():
    """Like Gelita log_tender_activity: action + sub_status_change when status unchanged."""
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(
            from_status=StatusType.COMPLETED,
            from_sub_status=StatusSubType.REMINDER_1_SENT,
        ),
        shipment_id="1000324895",
        outcome="skipped",
        activity_log_service=svc,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_sub_status == StatusSubType.UPLOADED_TO_TMS


def test_record_skipped_when_already_on_tms_action_only():
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(
            from_status=StatusType.COMPLETED,
            from_sub_status=StatusSubType.UPLOADED_TO_TMS,
        ),
        shipment_id="1000324895",
        outcome="skipped",
        activity_log_service=svc,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION


def test_record_uploaded_activity_with_null_workflow_run_id():
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(workflow_run_id=None),
        shipment_id="1000324895",
        outcome="uploaded",
        activity_log_service=svc,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert sequence.workflow_run_id is None


def test_record_failed_activity_marks_failed():
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(),
        shipment_id="1000324895",
        outcome="failed",
        activity_log_service=svc,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].to_status == StatusType.FAILED


def test_manual_from_pending_review_normalizes_then_completes() -> None:
    svc = MagicMock()
    svc.record_sequence.return_value = MagicMock()

    record_pod_tms_upload_activity(
        scope=_scope(
            from_status=StatusType.PENDING_REVIEW,
            from_sub_status=StatusSubType.DOCUMENT_PROCESSED,
        ),
        shipment_id="1000324895",
        outcome="uploaded",
        activity_log_service=svc,
        is_manual=True,
    )

    sequence = svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 3
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].from_status == StatusType.PENDING_REVIEW
    assert sequence.steps[0].to_status == StatusType.PROCESSING
    assert sequence.steps[1].activity_type == ActivityType.ACTION
    assert sequence.steps[2].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[2].from_status == StatusType.PROCESSING
    assert sequence.steps[2].to_status == StatusType.COMPLETED
    assert sequence.steps[2].to_sub_status == StatusSubType.UPLOADED_TO_TMS
    assert sequence.steps[0].metadata is None
    assert sequence.steps[2].metadata is None
