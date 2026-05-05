from app.workflows.contracts import WorkflowTemplateContract


WORKFLOW_TEMPLATE_CONTRACTS = {
    "pod_lifecycle": WorkflowTemplateContract(
        workflow_name="pod_lifecycle",
        operation="pod",
        version="1.0.0",
        description="Unified POD lifecycle workflow with event-driven branches.",
        event_types=["route_completed", "email_received", "reminder_due"],
        required_state_keys=["event_type"],
        optional_state_keys=[
            "shipment_id",
            "load_id",
            "thread_id",
            "attachments",
            "workflow_correlation_payload",
            "to",
            "subject",
            "body",
            "account_id",
            "reminder_step",
        ],
    ),
    "ratecon": WorkflowTemplateContract(
        workflow_name="ratecon",
        operation="ratecon",
        version="1.0.0",
        description="Rate confirmation workflow; resolves Turvo load_id to shipment_id (extend later).",
        event_types=["route_completed", "email_received", "reminder_due"],
        required_state_keys=["load_id"],
        optional_state_keys=[
            "event_type",
            "app_user_id",
            "thread_id",
            "shipment_id",
            "email_id",
            "account_id",
            "attachments",
            "has_attachments",
            "workflow_correlation_payload",
            "ratecon_correlation_thread_persist",
            "ratecon_s3_upload",
        ],
    ),
}
