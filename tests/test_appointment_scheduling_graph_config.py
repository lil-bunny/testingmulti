"""Smoke tests for appointment_scheduling workflow graph config."""

from __future__ import annotations

from app.configs.workflow_configs import WORKFLOW_CONFIGS


def test_appointment_scheduling_pickup_routes_through_prepare() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    route_map = cfg["routers"]["route_event"]["map"]
    prepare_router = cfg["routers"]["prepare_appointment_ingress"]

    assert route_map["turvo_pickup_changed"] == "prepare_appointment_ingress"
    assert "prepare_appointment_ingress" in cfg["nodes"]
    assert prepare_router["map"]["continue"] == "read_appointment_lifecycle"
    assert prepare_router["map"]["end"] == "end"


def test_appointment_scheduling_intake_tail_includes_teams_notify() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    nodes = cfg["nodes"]
    edges = [tuple(edge) for edge in cfg["edges"]]

    assert "notify_appointment_draft_teams" in nodes
    assert ("persist_appointment_draft_ready", "notify_appointment_draft_teams") in edges
    assert ("notify_appointment_draft_teams", "end") in edges


def test_appointment_scheduling_confirm_tail_includes_turvo_tender() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    nodes = cfg["nodes"]
    edges = [tuple(edge) for edge in cfg["edges"]]

    assert "apply_turvo_tender_status" in nodes
    assert ("send_appointment_confirmation_reply", "apply_turvo_tender_status") in edges
    assert ("apply_turvo_tender_status", "record_appointment_reply_completed") in edges


def test_appointment_scheduling_classify_reply_router_map() -> None:
    cfg = WORKFLOW_CONFIGS["appointment_scheduling"]
    classify_map = cfg["routers"]["classify_appointment_customer_reply"]["map"]
    edges = [tuple(edge) for edge in cfg["edges"]]

    assert classify_map["accepted"] == "apply_ascend_dropoff_appointment"
    assert classify_map["rejected"] == "record_appointment_reply_rejected"
    assert classify_map["do_nothing"] == "end"
    assert "record_appointment_reply_rejected" in cfg["nodes"]
    assert ("record_appointment_reply_rejected", "end") in edges
