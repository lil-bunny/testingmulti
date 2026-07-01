"""Tests for driver assignment activity log description helpers."""

from app.domain.driver_assignment.activity_log_descriptions import (
    format_driver_details_llm_action,
    format_driver_reminder_sent_action,
)


def test_format_driver_reminder_sent_action() -> None:
    assert format_driver_reminder_sent_action(step=2) == "Driver reminder 2 sent"


def test_format_driver_details_llm_action() -> None:
    text = format_driver_details_llm_action(
        decision="complete",
        reason="name and phone present",
        confidence=0.91,
    )
    assert text == (
        "Driver details LLM classified reply as complete confidence=0.91: "
        "name and phone present"
    )
