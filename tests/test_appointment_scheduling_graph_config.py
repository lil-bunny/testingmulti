"""Smoke tests for appointment_scheduling workflow graph config."""

from __future__ import annotations

from app.configs.workflow_configs import WORKFLOW_CONFIGS


def test_appointment_scheduling_intake_tail_includes_teams_notify() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    nodes = cfg["nodes"]
    edges = [tuple(edge) for edge in cfg["edges"]]

    assert "notify_appointment_scheduling_draft_teams" in nodes
    assert ("persist_scheduling_draft_ready", "notify_appointment_scheduling_draft_teams") in edges
    assert ("notify_appointment_scheduling_draft_teams", "end") in edges


def test_appointment_scheduling_confirm_tail_includes_turvo_tender() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    nodes = cfg["nodes"]
    edges = [tuple(edge) for edge in cfg["edges"]]

    assert "apply_turvo_tender_status" in nodes
    assert ("send_appointment_confirmation_reply", "apply_turvo_tender_status") in edges
    assert ("apply_turvo_tender_status", "record_appointment_reply_completed") in edges
