from app.workflows.nodes.process_pod import process_pod
from app.workflows.nodes.email import classify_inbound_email, ingest_email, send_email
from app.workflows.nodes.noop import noop_pod_followup_marker
from app.workflows.nodes.pod_request import (
    branch_after_send_email_pod_request,
    check_pod_request_triggered,
    send_email_continue,
)
from app.workflows.nodes.workflow_correlation import read_workflow_correlation, update_workflow_correlation
from app.workflows.nodes.system import end, route_event
from app.workflows.nodes.turvo import (
    check_existing_pod,
    get_shipment,
    refresh_pod_before_send_email,
    update_shipment,
)


NODE_REGISTRY = {
    "get_shipment": get_shipment,
    "check_existing_pod": check_existing_pod,
    "refresh_pod_before_send_email": refresh_pod_before_send_email,
    "update_shipment": update_shipment,
    "send_email": send_email,
    "noop_pod_followup_marker": noop_pod_followup_marker,
    "check_pod_request_triggered": check_pod_request_triggered,
    "branch_after_send_email_pod_request": branch_after_send_email_pod_request,
    "send_email_continue": send_email_continue,
    "ingest_email": ingest_email,
    "classify_inbound_email": classify_inbound_email,
    "read_workflow_correlation": read_workflow_correlation,
    "update_workflow_correlation": update_workflow_correlation,
    "process_pod": process_pod,
    "route_event": route_event,
    "end": end,
}
