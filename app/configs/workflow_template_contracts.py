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
        ],
    ),
}
