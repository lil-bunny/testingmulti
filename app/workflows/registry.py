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
from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params
from app.workflows.nodes.send_tender_email import send_tender_email
from app.workflows.nodes.log_tender_activity import log_tender_activity
from app.workflows.nodes.update_awaiting_response import update_awaiting_response
from app.workflows.nodes.schedule_tender_reminders import schedule_tender_reminders
from app.workflows.nodes.record_ack_received import classify_carrier_ack, record_ack_received
from app.workflows.nodes.record_tender_created_activity import record_tender_created_activity
from app.workflows.nodes.send_tender_reminder import send_tender_reminder
from app.workflows.nodes.update_reminder_status import update_reminder_status
from app.workflows.nodes.escalate_tender import escalate_tender
from app.workflows.nodes.tenders import read_tender_row

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
    "calculate_tender_params": calculate_tender_params,
    "send_tender_email": send_tender_email,
    "log_tender_activity": log_tender_activity,
    "update_awaiting_response": update_awaiting_response,
    "schedule_tender_reminders": schedule_tender_reminders,
    "classify_carrier_ack": classify_carrier_ack,
    "record_ack_received": record_ack_received,
    "record_tender_created_activity": record_tender_created_activity,
    "read_tender_row": read_tender_row,
    "send_tender_reminder": send_tender_reminder,
    "update_reminder_status": update_reminder_status,
    "escalate_tender": escalate_tender,
    "end": end,
}
