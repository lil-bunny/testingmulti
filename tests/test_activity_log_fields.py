"""Tests for ``build_activity_log_status_fields``."""

from __future__ import annotations

from app.domain.activity_log_fields import build_activity_log_status_fields
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _command(**kwargs) -> LifecycleTransitionCommand:
    base = dict(
        tenant_id=TENANT,
        workflow_lifecycle_id=LIFECYCLE,
        workflow_run_id=RUN,
        activity_type=ActivityType.STATUS_CHANGE,
    )
    base.update(kwargs)
    return LifecycleTransitionCommand(**base)


def test_action_snapshot_equals_current() -> None:
    log_from, log_to, log_from_sub, log_to_sub = build_activity_log_status_fields(
        _command(activity_type=ActivityType.ACTION),
        current_status=StatusType.PENDING_REVIEW,
        current_sub=StatusSubType.TENDER_SENT_TO_CARRIER,
    )
    assert log_from == log_to == StatusType.PENDING_REVIEW
    assert log_from_sub == log_to_sub == StatusSubType.TENDER_SENT_TO_CARRIER


def test_action_ignores_command_to_fields_in_builder() -> None:
    log_from, log_to, log_from_sub, log_to_sub = build_activity_log_status_fields(
        _command(
            activity_type=ActivityType.ACTION,
            to_status=StatusType.COMPLETED,
            to_sub_status=StatusSubType.ACCEPTED,
        ),
        current_status=StatusType.PROCESSING,
        current_sub=StatusSubType.TENDER_CREATED,
    )
    assert log_from == log_to == StatusType.PROCESSING
    assert log_from_sub == log_to_sub == StatusSubType.TENDER_CREATED


def test_sub_status_change_keeps_top_level_when_to_status_omitted() -> None:
    log_from, log_to, log_from_sub, log_to_sub = build_activity_log_status_fields(
        _command(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_sub_status=StatusSubType.ESCALATED,
        ),
        current_status=StatusType.PENDING_REVIEW,
        current_sub=StatusSubType.REMINDER_2_SENT,
    )
    assert log_from == log_to == StatusType.PENDING_REVIEW
    assert log_from_sub == StatusSubType.REMINDER_2_SENT
    assert log_to_sub == StatusSubType.ESCALATED
