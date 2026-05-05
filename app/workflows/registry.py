# from app.workflows.nodes.process_pod import process_pod
from app.workflows.nodes.pod import classify_attachments, ratecon_analysis, pod_analysis, pod_vs_ratecon_analysis
from app.workflows.nodes.email import check_email_attachments, ingest_email, send_email, get_email_attachments
from app.workflows.nodes.noop import noop_pod_followup_marker
from app.workflows.nodes.pod_request import (
    branch_after_send_email_pod_request,
    check_pod_request_triggered,
    mark_pod_schedule_context,
    send_email_continue,
)
from app.workflows.nodes.workflow_correlation import (
    add_thread_for_shipment,
    check_ratecon_workflow_correlation,
    read_workflow_correlation,
    update_workflow_correlation,
)
from app.workflows.nodes.system import end, route_event
from app.workflows.nodes.turvo import (
    check_existing_pod,
    get_shipment,
    refresh_pod_before_send_email,
    resolve_load_to_shipment,
    update_shipment,
    upload_to_turvo,
)

NODE_REGISTRY = {
    "get_shipment": get_shipment,
    "resolve_load_to_shipment": resolve_load_to_shipment,
    "check_existing_pod": check_existing_pod,
    "refresh_pod_before_send_email": refresh_pod_before_send_email,
    "upload_to_turvo": upload_to_turvo,
    "update_shipment": update_shipment,
    "send_email": send_email,
    "mark_pod_schedule_context": mark_pod_schedule_context,
    "noop_pod_followup_marker": noop_pod_followup_marker,
    "check_pod_request_triggered": check_pod_request_triggered,
    "branch_after_send_email_pod_request": branch_after_send_email_pod_request,
    "send_email_continue": send_email_continue,
    "ingest_email": ingest_email,
    "check_email_attachments": check_email_attachments,
    "get_email_attachments": get_email_attachments,
    "classify_attachments": classify_attachments,
    "ratecon_analysis": ratecon_analysis,
    "pod_analysis": pod_analysis,
    "pod_vs_ratecon_analysis": pod_vs_ratecon_analysis,
    "read_workflow_correlation": read_workflow_correlation,
    "check_ratecon_workflow_correlation": check_ratecon_workflow_correlation,
    "add_thread_for_shipment": add_thread_for_shipment,
    "update_workflow_correlation": update_workflow_correlation,
    "route_event": route_event,
    "end": end,
}
