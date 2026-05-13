from app.workflows.nodes.ratecon import upload_ratecon_attachments
from app.workflows.nodes.pod import classify_attachments, ratecon_analysis, pod_analysis, pod_vs_ratecon_analysis
from app.workflows.nodes.email import send_email, get_email_attachments
from app.workflows.nodes.pod_request import (
    check_pod_request_triggered,
    record_and_schedule_pod_request,
    record_reminder_run,
)
from app.workflows.nodes.workflow_lifecycle import (
    check_ratecon_workflow_lifecycle,
    read_workflow_lifecycle,
    resolve_workflow_lifecycle,
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
    "check_pod_request_triggered": check_pod_request_triggered,
    "record_and_schedule_pod_request": record_and_schedule_pod_request,
    "record_reminder_run": record_reminder_run,
    "get_email_attachments": get_email_attachments,
    "classify_attachments": classify_attachments,
    "ratecon_analysis": ratecon_analysis,
    "pod_analysis": pod_analysis,
    "pod_vs_ratecon_analysis": pod_vs_ratecon_analysis,
    "read_workflow_lifecycle": read_workflow_lifecycle,
    "check_ratecon_workflow_lifecycle": check_ratecon_workflow_lifecycle,
    "upload_ratecon_attachments": upload_ratecon_attachments,
    "resolve_workflow_lifecycle": resolve_workflow_lifecycle,
    "route_event": route_event,
    "end": end,
}
