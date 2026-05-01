# from app.workflows.nodes.process_pod import process_pod
from app.workflows.nodes.pod import classify_attachments, ratecon_analysis, pod_analysis, pod_vs_ratecon_analysis
from app.workflows.nodes.email import check_email_attachments, ingest_email, send_email, get_email_attachments
from app.workflows.nodes.workflow_correlation import read_workflow_correlation, update_workflow_correlation
from app.workflows.nodes.system import end, route_event
from app.workflows.nodes.turvo import check_existing_pod, get_shipment, update_shipment, upload_to_turvo

NODE_REGISTRY = {
    "get_shipment": get_shipment,
    "check_existing_pod": check_existing_pod,
    "upload_to_turvo": upload_to_turvo,
    "update_shipment": update_shipment,
    "send_email": send_email,
    "ingest_email": ingest_email,
    "check_email_attachments": check_email_attachments,
    "get_email_attachments": get_email_attachments,
    "classify_attachments": classify_attachments,
    "ratecon_analysis": ratecon_analysis,
    "pod_analysis": pod_analysis,
    "pod_vs_ratecon_analysis": pod_vs_ratecon_analysis,
    "read_workflow_correlation": read_workflow_correlation,
    "update_workflow_correlation": update_workflow_correlation,
    "route_event": route_event,
    "end": end,
}