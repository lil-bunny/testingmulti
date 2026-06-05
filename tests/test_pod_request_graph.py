"""Graph wiring for POD-request idempotency nodes."""

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.workflows.validators import validate_graph_definition


def test_pod_lifecycle_pod_request_graph():
    graph = WORKFLOW_CONFIGS["pod_lifecycle"]
    validate_graph_definition(graph)

    names = graph["nodes"]
    assert "check_pod_request_triggered" in names
    assert "record_and_schedule_pod_request" in names
    assert "record_reminder_run" in names

    routers = graph["routers"]
    assert "check_pod_request_triggered" in routers
    assert routers["check_pod_request_triggered"]["router"] == "pod_request_triggered_router"
    assert "check_existing_pod" in routers
    assert routers["check_existing_pod"]["map"]["skip_send"] == "end"
    assert routers["check_existing_pod"]["map"]["schedule_initial"] == "record_and_schedule_pod_request"
    assert routers["check_existing_pod"]["map"]["send_now"] == "send_email"

    edges = [tuple(e) for e in graph["edges"]]
    assert ("send_email", "record_reminder_run") in edges
    assert ("record_reminder_run", "end") in edges
    assert ("record_and_schedule_pod_request", "end") in edges


def test_ratecon_graph():
    graph = WORKFLOW_CONFIGS["ratecon"]
    validate_graph_definition(graph)

    assert graph["entry"] == "resolve_load_to_shipment"
    assert graph["exit"] == "end"
    assert graph["nodes"] == [
        "resolve_load_to_shipment",
        "get_shipment",
        "link_shipment_locations",
        "resolve_workflow_lifecycle",
        "upload_ratecon_attachments",
        "check_ratecon_workflow_lifecycle",
        "end",
    ]
    edges = [tuple(e) for e in graph["edges"]]
    assert ("resolve_load_to_shipment", "get_shipment") in edges
    assert ("get_shipment", "link_shipment_locations") in edges
    assert ("link_shipment_locations", "resolve_workflow_lifecycle") in edges
    assert ("resolve_workflow_lifecycle", "upload_ratecon_attachments") in edges
    assert ("upload_ratecon_attachments", "check_ratecon_workflow_lifecycle") in edges
    assert ("check_ratecon_workflow_lifecycle", "end") in edges
    assert graph.get("routers") == {}
