"""Graph wiring for POD-request scheduling nodes."""

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.workflows.validators import validate_graph_definition


def test_pod_lifecycle_pod_request_graph():
    graph = WORKFLOW_CONFIGS["pod_lifecycle"]
    validate_graph_definition(graph)

    names = graph["nodes"]
    assert "ratecon_analysis" not in names
    assert "load_ratecon_analysis" in names
    assert "check_pod_request_triggered" not in names
    assert "record_and_schedule_pod_request" in names
    assert "record_pod_started_activity" in names
    assert "record_pod_reminder_activity" in names

    routers = graph["routers"]
    assert "check_pod_request_triggered" not in routers
    assert routers["route_event"]["map"]["route_completed"] == "get_shipment"
    assert "check_existing_pod" in routers
    assert routers["check_existing_pod"]["map"]["skip_send"] == "end"
    assert routers["check_existing_pod"]["map"]["schedule_initial"] == "record_and_schedule_pod_request"
    assert routers["check_existing_pod"]["map"]["send_now"] == "send_email"

    edges = [tuple(e) for e in graph["edges"]]
    assert ("get_email_attachments", "load_ratecon_analysis") in edges
    assert ("ratecon_analysis", "classify_attachments") not in edges
    assert routers["get_shipment"]["map"]["manual_pod_valid"] == "load_ratecon_analysis"
    assert routers["load_ratecon_analysis"]["router"] == "ratecon_cache_router"
    assert routers["load_ratecon_analysis"]["map"]["ready"] == "classify_attachments"
    assert routers["load_ratecon_analysis"]["map"]["missing"] == "end"
    assert ("send_email", "record_pod_reminder_activity") in edges
    assert ("record_pod_reminder_activity", "end") in edges
    assert ("record_and_schedule_pod_request", "record_pod_started_activity") in edges
    assert ("record_pod_started_activity", "end") in edges


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
        "record_ratecon_received_activity",
        "upload_ratecon_attachments",
        "record_ratecon_upload_activity",
        "ratecon_analysis",
        "record_ratecon_processed_activity",
        "check_ratecon_workflow_lifecycle",
        "end",
    ]
    edges = [tuple(e) for e in graph["edges"]]
    assert ("resolve_load_to_shipment", "get_shipment") in edges
    assert ("get_shipment", "link_shipment_locations") in edges
    assert ("link_shipment_locations", "resolve_workflow_lifecycle") in edges
    assert ("resolve_workflow_lifecycle", "record_ratecon_received_activity") in edges
    assert ("record_ratecon_received_activity", "upload_ratecon_attachments") in edges
    assert ("upload_ratecon_attachments", "record_ratecon_upload_activity") in edges
    assert ("record_ratecon_upload_activity", "ratecon_analysis") in edges
    assert ("ratecon_analysis", "record_ratecon_processed_activity") in edges
    assert ("record_ratecon_processed_activity", "check_ratecon_workflow_lifecycle") in edges
    assert ("check_ratecon_workflow_lifecycle", "end") in edges
    assert graph.get("routers") == {}
