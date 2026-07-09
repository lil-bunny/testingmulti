"""Unit tests for driver_assignment reminder ladder helpers."""

from __future__ import annotations

from app.domain.driver_assignment.reminder_ladder import (
    append_sent_schedule_step,
    next_sequential_reminder_step,
    schedule_reminder_step_from_payload,
    sent_schedule_steps_from_metadata,
    sequential_reminder_step_from_sub_status,
    should_resolve_sequential_reminder_step,
)
from app.models.status import StatusSubType


def test_sequential_reminder_step_from_sub_status() -> None:
    assert sequential_reminder_step_from_sub_status(StatusSubType.NONE.value) == 0
    assert sequential_reminder_step_from_sub_status(StatusSubType.REMINDER_1_SENT.value) == 1
    assert sequential_reminder_step_from_sub_status(StatusSubType.REMINDER_4_SENT.value) == 4


def test_next_sequential_reminder_step() -> None:
    assert next_sequential_reminder_step(0) == 1
    assert next_sequential_reminder_step(3) == 4
    assert next_sequential_reminder_step(4) == 4


def test_sent_schedule_steps_from_metadata() -> None:
    assert sent_schedule_steps_from_metadata({}) == frozenset()
    assert sent_schedule_steps_from_metadata(
        {"driver_assignment_sent_schedule_steps": [2, 3]}
    ) == frozenset({2, 3})


def test_append_sent_schedule_step() -> None:
    assert append_sent_schedule_step([2], 3) == [2, 3]
    assert append_sent_schedule_step([2, 3], 2) == [2, 3]


def test_schedule_reminder_step_from_payload_prefers_schedule_key() -> None:
    payload = {"schedule_reminder_step": 3, "reminder_step": 1}
    assert schedule_reminder_step_from_payload(payload) == 3


def test_schedule_reminder_step_from_payload_legacy_fallback() -> None:
    assert schedule_reminder_step_from_payload({"reminder_step": 2}) == 2


def test_should_resolve_sequential_reminder_step() -> None:
    assert should_resolve_sequential_reminder_step({"event_type": "reminder_due"}) is True
    assert not should_resolve_sequential_reminder_step(
        {"reminder_email_source": "driver_details_confirmation"}
    )
