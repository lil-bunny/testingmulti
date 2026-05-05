"""Graph wiring for POD-request idempotency nodes."""

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.workflows.validators import validate_graph_definition


def test_pod_lifecycle_pod_request_graph():
    graph = WORKFLOW_CONFIGS["pod_lifecycle"]
    validate_graph_definition(graph)

    names = graph["nodes"]
    assert "check_pod_request_triggered" in names
    assert "branch_after_send_email_pod_request" in names
    assert "refresh_pod_before_send_email" in names
    assert "noop_pod_followup_marker" in names

    routers = graph["routers"]
    assert "check_pod_request_triggered" in routers
    assert routers["check_pod_request_triggered"]["router"] == "pod_request_triggered"
    refresh_map = routers["refresh_pod_before_send_email"]["map"]
    assert refresh_map["send_now"] == "send_email"
    assert refresh_map["skip_send"] == "end"
    assert "check_existing_pod" in routers
    assert routers["check_existing_pod"]["map"]["skip_send"] == "end"

    edges = [tuple(e) for e in graph["edges"]]
    assert ("send_email", "branch_after_send_email_pod_request") in edges
    assert ("noop_pod_followup_marker", "refresh_pod_before_send_email") in edges
    assert ("process_pod", "noop_pod_followup_marker") not in edges
    assert ("check_existing_pod", "send_email") not in edges


def test_ratecon_graph():
    graph = WORKFLOW_CONFIGS["ratecon"]
    validate_graph_definition(graph)

    assert graph["entry"] == "resolve_load_to_shipment"
    assert graph["exit"] == "end"
    assert graph["nodes"] == [
        "resolve_load_to_shipment",
        "upload_ratecon_attachments",
        "check_ratecon_workflow_correlation",
        "add_thread_for_shipment",
        "end",
    ]
    edges = [tuple(e) for e in graph["edges"]]
    assert ("resolve_load_to_shipment", "upload_ratecon_attachments") in edges
    assert ("upload_ratecon_attachments", "check_ratecon_workflow_correlation") in edges
    assert ("check_ratecon_workflow_correlation", "add_thread_for_shipment") in edges
    assert ("add_thread_for_shipment", "end") in edges
    assert graph.get("routers") == {}
