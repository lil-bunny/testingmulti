from app.workflows.nodes.ratecon import upload_ratecon_attachments
from app.workflows.nodes.pod import (
    load_ratecon_analysis,
    merge_and_upload_pod_attachments,
    pod_analysis,
    pod_vs_ratecon_analysis,
    ratecon_analysis,
)
from app.workflows.nodes.email import send_email
from app.workflows.nodes.pod_request import (
    check_pod_reminder_eligibility,
    complete_pod_found_in_tms,
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
    link_shipment_locations,
    resolve_load_to_shipment,
    update_shipment,
    upload_to_turvo,
)
from app.workflows.nodes.gelita.calculate_tender_params import calculate_tender_params
from app.workflows.nodes.gelita.resolve_international_delivery_skip import (
    resolve_international_delivery_skip,
)
from app.workflows.nodes.gelita.resolve_pack_code_skip import (
    resolve_pack_code_skip,
)
from app.workflows.nodes.gelita.record_tender_business_warnings import (
    record_tender_business_warnings,
)
from app.workflows.nodes.send_tender_email import send_tender_email
from app.workflows.nodes.log_tender_activity import log_tender_activity
from app.workflows.nodes.record_tender_sent_to_carrier import record_tender_sent_to_carrier
from app.workflows.nodes.schedule_tender_reminders import schedule_tender_reminders
from app.workflows.nodes.record_ack_received import (
    classify_carrier_ack,
    guard_automatic_reply_ack,
    record_ack_received,
)
from app.workflows.nodes.record_tender_created_activity import record_tender_created_activity
from app.workflows.nodes.record_ratecon_activity import (
    record_ratecon_processed_activity,
    record_ratecon_received_activity,
    record_ratecon_upload_activity,
)
from app.workflows.nodes.enqueue_driver_assignment import (
    enqueue_driver_assignment_on_ratecon_complete,
)
from app.workflows.nodes.driver_assignment.nodes import (
    check_driver_assignment_eligibility,
    check_driver_escalation_eligibility,
    check_driver_reminder_eligibility,
    classify_driver_details,
    complete_driver_assignment_from_tms,
    escalate_driver_assignment,
    record_driver_assignment_started,
    record_driver_assignment_completed,
    record_driver_details_confirmation_sent,
    record_driver_reminder_sent,
    record_tms_driver_error,
    record_tms_driver_not_resolved,
    record_tms_driver_success,
    resolve_turvo_driver,
    route_driver_assignment_delayed_event,
    route_tms_searchable,
    schedule_driver_reminders,
    send_driver_details_confirmation,
    send_driver_details_partial_follow_up,
    send_driver_reminder,
)
from app.workflows.nodes.record_pod_activity import (
    record_pod_escalation_activity,
    record_pod_extraction_activity,
    record_pod_processed_activity,
    record_pod_reminder_activity,
    record_pod_started_activity,
    record_pod_upload_activity,
    record_pod_vs_ratecon_activity,
)
from app.workflows.nodes.record_pod_tms_upload_activity import (
    record_pod_tms_upload_activity,
)
from app.workflows.nodes.send_tender_reminder import send_tender_reminder
from app.workflows.nodes.update_reminder_status import update_reminder_status
from app.workflows.nodes.escalate_tender import escalate_tender
from app.workflows.nodes.routing_guide import (
    advance_carrier_routing_guide,
    evaluate_reject_routing_guide,
    evaluate_timeout_routing_guide,
)
from app.workflows.nodes.tenders import read_tender_row
from app.workflows.nodes.error_handler import record_workflow_failure_node

NODE_REGISTRY = {
    "get_shipment": get_shipment,
    "link_shipment_locations": link_shipment_locations,
    "resolve_load_to_shipment": resolve_load_to_shipment,
    "check_existing_pod": check_existing_pod,
    "refresh_pod_before_send_email": refresh_pod_before_send_email,
    "upload_to_turvo": upload_to_turvo,
    "update_shipment": update_shipment,
    "send_email": send_email,
    "record_and_schedule_pod_request": record_and_schedule_pod_request,
    "check_pod_reminder_eligibility": check_pod_reminder_eligibility,
    "complete_pod_found_in_tms": complete_pod_found_in_tms,
    "record_reminder_run": record_reminder_run,
    "load_ratecon_analysis": load_ratecon_analysis,
    "ratecon_analysis": ratecon_analysis,
    "merge_and_upload_pod_attachments": merge_and_upload_pod_attachments,
    "pod_analysis": pod_analysis,
    "pod_vs_ratecon_analysis": pod_vs_ratecon_analysis,
    "read_workflow_lifecycle": read_workflow_lifecycle,
    "check_ratecon_workflow_lifecycle": check_ratecon_workflow_lifecycle,
    "upload_ratecon_attachments": upload_ratecon_attachments,
    "resolve_workflow_lifecycle": resolve_workflow_lifecycle,
    "route_event": route_event,
    "calculate_tender_params": calculate_tender_params,
    "resolve_international_delivery_skip": resolve_international_delivery_skip,
    "resolve_pack_code_skip": resolve_pack_code_skip,
    "record_tender_business_warnings": record_tender_business_warnings,
    "send_tender_email": send_tender_email,
    "log_tender_activity": log_tender_activity,
    "record_tender_sent_to_carrier": record_tender_sent_to_carrier,
    "schedule_tender_reminders": schedule_tender_reminders,
    "guard_automatic_reply_ack": guard_automatic_reply_ack,
    "classify_carrier_ack": classify_carrier_ack,
    "record_ack_received": record_ack_received,
    "record_tender_created_activity": record_tender_created_activity,
    "record_ratecon_received_activity": record_ratecon_received_activity,
    "record_ratecon_upload_activity": record_ratecon_upload_activity,
    "record_ratecon_processed_activity": record_ratecon_processed_activity,
    "enqueue_driver_assignment_on_ratecon_complete": enqueue_driver_assignment_on_ratecon_complete,
    "check_driver_assignment_eligibility": check_driver_assignment_eligibility,
    "check_driver_reminder_eligibility": check_driver_reminder_eligibility,
    "route_driver_assignment_delayed_event": route_driver_assignment_delayed_event,
    "check_driver_escalation_eligibility": check_driver_escalation_eligibility,
    "escalate_driver_assignment": escalate_driver_assignment,
    "send_driver_reminder": send_driver_reminder,
    "record_driver_reminder_sent": record_driver_reminder_sent,
    "record_driver_assignment_started": record_driver_assignment_started,
    "schedule_driver_reminders": schedule_driver_reminders,
    "classify_driver_details": classify_driver_details,
    "route_tms_searchable": route_tms_searchable,
    "resolve_turvo_driver": resolve_turvo_driver,
    "record_tms_driver_success": record_tms_driver_success,
    "complete_driver_assignment_from_tms": complete_driver_assignment_from_tms,
    "record_tms_driver_not_resolved": record_tms_driver_not_resolved,
    "record_tms_driver_error": record_tms_driver_error,
    "send_driver_details_confirmation": send_driver_details_confirmation,
    "record_driver_details_confirmation_sent": record_driver_details_confirmation_sent,
    "record_driver_assignment_completed": record_driver_assignment_completed,
    "send_driver_details_partial_follow_up": send_driver_details_partial_follow_up,
    "record_pod_started_activity": record_pod_started_activity,
    "record_pod_reminder_activity": record_pod_reminder_activity,
    "record_pod_escalation_activity": record_pod_escalation_activity,
    "record_pod_upload_activity": record_pod_upload_activity,
    "record_pod_extraction_activity": record_pod_extraction_activity,
    "record_pod_vs_ratecon_activity": record_pod_vs_ratecon_activity,
    "record_pod_processed_activity": record_pod_processed_activity,
    "record_pod_tms_upload_activity": record_pod_tms_upload_activity,
    "read_tender_row": read_tender_row,
    "send_tender_reminder": send_tender_reminder,
    "update_reminder_status": update_reminder_status,
    "escalate_tender": escalate_tender,
    "evaluate_reject_routing_guide": evaluate_reject_routing_guide,
    "evaluate_timeout_routing_guide": evaluate_timeout_routing_guide,
    "advance_carrier_routing_guide": advance_carrier_routing_guide,
    "record_workflow_failure": record_workflow_failure_node,
    "end": end,
}
