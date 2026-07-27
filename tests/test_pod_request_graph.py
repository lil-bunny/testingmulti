"""Graph wiring for POD-request scheduling nodes."""

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.workflows.validators import validate_graph_definition


def test_pod_lifecycle_pod_request_graph():
    graph = WORKFLOW_CONFIGS["pod_lifecycle"]
    validate_graph_definition(graph)

    names = graph["nodes"]
    assert "ratecon_analysis" not in names
    assert "load_ratecon_analysis" not in names
    assert "pod_vs_ratecon_analysis" not in names
    assert "record_pod_vs_ratecon_activity" not in names
    assert "check_pod_request_triggered" not in names
    assert "record_and_schedule_pod_request" in names
    assert "record_pod_started_activity" in names
    assert "record_pod_reminder_activity" in names
    assert "record_pod_upload_activity" in names
    assert "merge_and_upload_pod_attachments" in names
    assert "record_pod_extraction_activity" in names
    assert "record_pod_processed_activity" in names
    assert "notify_pod_analysis_teams" in names
    assert "check_pod_reminder_eligibility" in names
    assert "complete_pod_found_in_tms" in names

    routers = graph["routers"]
    assert "check_pod_request_triggered" not in routers
    assert routers["route_event"]["map"]["route_completed"] == "get_shipment"
    assert "check_existing_pod" in routers
    assert routers["check_existing_pod"]["map"]["skip_send"] == "end"
    assert routers["check_existing_pod"]["map"]["exists_on_reminder"] == "complete_pod_found_in_tms"
    assert routers["check_existing_pod"]["map"]["schedule_initial"] == "record_and_schedule_pod_request"
    assert routers["check_existing_pod"]["map"]["send_now"] == "check_pod_reminder_eligibility"
    assert routers["check_pod_reminder_eligibility"]["router"] == "pod_reminder_eligibility_router"
    assert routers["check_pod_reminder_eligibility"]["map"]["eligible"] == "send_email"
    assert routers["check_pod_reminder_eligibility"]["map"]["skip"] == "end"

    edges = [tuple(e) for e in graph["edges"]]
    assert "get_email_attachments" not in names
    assert "classify_attachments" not in names
    assert routers["get_shipment"]["map"]["valid_shipment_status"] == "merge_and_upload_pod_attachments"
    assert routers["get_shipment"]["map"]["manual_pod_stored"] == "upload_to_turvo"
    assert routers["get_shipment"]["map"]["manual_pod_process"] == "merge_and_upload_pod_attachments"
    assert "load_ratecon_analysis" not in routers
    assert ("merge_and_upload_pod_attachments", "record_pod_upload_activity") in edges
    assert ("record_pod_upload_activity", "pod_analysis") in edges
    assert ("pod_analysis", "record_pod_extraction_activity") in edges
    assert ("record_pod_extraction_activity", "capture_turvo_shipment_snapshot") in edges
    assert ("capture_turvo_shipment_snapshot", "pod_scoring") in edges
    assert ("pod_scoring", "record_pod_processed_activity") in edges
    assert ("record_pod_processed_activity", "notify_pod_analysis_teams") in edges
    assert ("record_pod_processed_activity", "update_shipment") not in edges
    assert ("upload_to_turvo", "record_pod_tms_upload_activity") in edges
    assert ("record_pod_tms_upload_activity", "end") in edges
    assert routers["notify_pod_analysis_teams"]["router"] == "post_pod_processing_router"
    assert routers["notify_pod_analysis_teams"]["map"]["manual"] == "upload_to_turvo"
    assert routers["notify_pod_analysis_teams"]["map"]["email"] == "update_shipment"
    assert "record_pod_tms_upload_activity" not in routers
    assert ("pod_scoring", "upload_to_turvo") not in edges
    assert ("check_pod_reminder_eligibility", "send_email") not in edges
    assert ("send_email", "record_pod_reminder_activity") in edges
    assert ("record_pod_reminder_activity", "end") in edges
    assert ("record_and_schedule_pod_request", "record_pod_started_activity") in edges
    assert ("record_pod_started_activity", "end") in edges
    assert ("complete_pod_found_in_tms", "end") in edges


def test_ratecon_graph():
    graph = WORKFLOW_CONFIGS["ratecon"]
    validate_graph_definition(graph)

    assert graph["entry"] == "resolve_load_to_shipment"
    assert graph["exit"] == "end"
    assert "ratecon_analysis" not in graph["nodes"]
    assert graph["nodes"] == [
        "resolve_load_to_shipment",
        "get_shipment",
        "link_shipment_locations",
        "resolve_workflow_lifecycle",
        "record_ratecon_received_activity",
        "cache_ratecon_page_count",
        "record_ratecon_processed_activity",
        "enqueue_driver_assignment_on_ratecon_complete",
        "check_ratecon_workflow_lifecycle",
        "end",
    ]
    edges = [tuple(e) for e in graph["edges"]]
    assert ("resolve_load_to_shipment", "get_shipment") in edges
    assert ("get_shipment", "link_shipment_locations") in edges
    assert ("link_shipment_locations", "resolve_workflow_lifecycle") in edges
    assert ("resolve_workflow_lifecycle", "record_ratecon_received_activity") in edges
    assert ("record_ratecon_received_activity", "cache_ratecon_page_count") in edges
    assert ("cache_ratecon_page_count", "record_ratecon_processed_activity") in edges
    assert (
        "record_ratecon_processed_activity",
        "enqueue_driver_assignment_on_ratecon_complete",
    ) in edges
    assert (
        "enqueue_driver_assignment_on_ratecon_complete",
        "check_ratecon_workflow_lifecycle",
    ) in edges
    assert ("check_ratecon_workflow_lifecycle", "end") in edges
    assert graph.get("routers") == {}
