from app.workflows.nodes.process_pod import process_pod
from app.workflows.nodes.email import check_email_attachments, ingest_email, send_email, get_email_attachments
from app.workflows.nodes.workflow_correlation import read_workflow_correlation, update_workflow_correlation
from app.workflows.nodes.system import end, route_event
from app.workflows.nodes.turvo import check_existing_pod, get_shipment, update_shipment


NODE_REGISTRY = {
    "get_shipment": get_shipment,
    "check_existing_pod": check_existing_pod,
    "update_shipment": update_shipment,
    "send_email": send_email,
    "ingest_email": ingest_email,
    "check_email_attachments": check_email_attachments,
    "get_email_attachments": get_email_attachments,
    "read_workflow_correlation": read_workflow_correlation,
    "update_workflow_correlation": update_workflow_correlation,
    "process_pod": process_pod,
    "route_event": route_event,
    "end": end,
}