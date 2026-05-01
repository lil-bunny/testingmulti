WORKFLOW_CONFIGS = {
    "pod_lifecycle": {
        "entry": "route_event",
        "exit": "end",
        "nodes": [
            "route_event",
            "get_shipment",
            "read_workflow_correlation",
            "check_existing_pod",
            "send_email",
            "ingest_email",
            "check_email_attachments",
            "get_email_attachments",
            "classify_attachments",
            "ratecon_analysis",
            "pod_analysis",
            "pod_vs_ratecon_analysis",
            "upload_to_turvo",
            "update_shipment",
            "end",
        ],
        "edges": [
            ["ingest_email", "check_email_attachments"],
            ["get_email_attachments", "ratecon_analysis"],
            ["ratecon_analysis","classify_attachments"],
            ["classify_attachments", "pod_analysis"],
            ["pod_analysis", "pod_vs_ratecon_analysis"],
            ["pod_vs_ratecon_analysis", "upload_to_turvo"],
            ["upload_to_turvo", "update_shipment"],
            ["update_shipment", "end"],
            ["send_email", "end"],
        ],
        "routers": {
            "route_event": {
                "router": "event_type",
                "map": {
                    "route_completed": "get_shipment",
                    "email_received": "ingest_email",
                    "reminder_due": "check_existing_pod",
                },
            },
            "get_shipment": {
                "router": "shipment_router",
                "map": {
                    "convoy": "end",
                    "non_convoy": "read_workflow_correlation",
                    # Pod reply workflow
                    "valid_shipment_status": "get_email_attachments",
                    "invalid_shipment_status": "end",
                },
            },
            "check_existing_pod": {
                "router": "pod_exists",
                "map": {"exists": "end", "missing": "send_email"},
            },
            "check_email_attachments": {
                "router": "pod_reply",
                "map": {"is_reply": "read_workflow_correlation", "missing": "end"},
            },
            "read_workflow_correlation": {
                "router": "read_workflow_correlation",
                "map": {"is_found": "get_shipment", "check_existing_pod": "check_existing_pod", "missing": "end"},
            }
        },
    },
}