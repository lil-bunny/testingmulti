WORKFLOW_CONFIGS = {
    "pod_lifecycle": {
        "entry": "route_event",
        "exit": "end",
        "nodes": [
            "route_event",
            "get_shipment",
            "check_pod_request_triggered",
            "read_workflow_correlation",
            "check_existing_pod",
            "refresh_pod_before_send_email",
            "send_email",
            "mark_pod_schedule_context",
            "branch_after_send_email_pod_request",
            "send_email_continue",
            "noop_pod_followup_marker",
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
            ["send_email", "branch_after_send_email_pod_request"],
            ["mark_pod_schedule_context", "branch_after_send_email_pod_request"],
            ["branch_after_send_email_pod_request", "send_email_continue"],
            ["send_email_continue", "end"],
            ["noop_pod_followup_marker", "refresh_pod_before_send_email"],
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
                    "non_convoy": "check_pod_request_triggered",
                    # Pod reply workflow
                    "valid_shipment_status": "get_email_attachments",
                    "invalid_shipment_status": "end",
                },
            },
            "check_pod_request_triggered": {
                "router": "pod_request_triggered_router",
                "map": {
                    "blocked": "end",
                    "continue": "read_workflow_correlation",
                },
            },
            "check_existing_pod": {
                "router": "pod_missing_dispatch",
                "map": {
                    "exists": "end",
                    "schedule_initial": "mark_pod_schedule_context",
                    "send_now": "send_email",
                    "skip_send": "end",
                },
            },
            "refresh_pod_before_send_email": {
                "router": "pod_missing_dispatch",
                "map": {
                    "exists": "end",
                    "schedule_initial": "mark_pod_schedule_context",
                    "send_now": "send_email",
                    "skip_send": "end",
                },
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
    "ratecon": {
        "entry": "resolve_load_to_shipment",
        "exit": "end",
        "nodes": [
            "resolve_load_to_shipment",
            "upload_ratecon_attachments",
            "check_ratecon_workflow_correlation",
            "add_thread_for_shipment",
            "end",
        ],
        "edges": [
            ["resolve_load_to_shipment", "upload_ratecon_attachments"],
            ["upload_ratecon_attachments", "check_ratecon_workflow_correlation"],
            ["check_ratecon_workflow_correlation", "add_thread_for_shipment"],
            ["add_thread_for_shipment", "end"],
        ],
        "routers": {},
    },
}
