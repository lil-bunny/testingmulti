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
            "branch_after_send_email_pod_request",
            "send_email_continue",
            "noop_pod_followup_marker",
            "ingest_email",
            "classify_inbound_email",
            "update_workflow_correlation",
            "process_pod",
            "update_shipment",
            "end",
        ],
        "edges": [
            ["read_workflow_correlation", "check_existing_pod"],
            ["ingest_email", "classify_inbound_email"],
            ["update_workflow_correlation", "process_pod"],
            ["update_shipment", "end"],
            ["send_email", "branch_after_send_email_pod_request"],
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
                "router": "convoy",
                "map": {
                    "convoy": "end",
                    "non_convoy": "check_pod_request_triggered",
                },
            },
            "check_pod_request_triggered": {
                "router": "pod_request_triggered",
                "map": {
                    "blocked": "end",
                    "continue": "read_workflow_correlation",
                },
            },
            "check_existing_pod": {
                "router": "pod_exists",
                "map": {"exists": "end", "missing": "send_email"},
            },
            "refresh_pod_before_send_email": {
                "router": "pod_exists",
                "map": {"exists": "end", "missing": "send_email"},
            },
            "classify_inbound_email": {
                "router": "pod_reply",
                "map": {"is_reply": "update_workflow_correlation", "ignore": "end"},
            },
            "process_pod": {
                "router": "pod_exists",
                "map": {
                    "exists": "update_shipment",
                    "missing": "noop_pod_followup_marker",
                },
            },
            "branch_after_send_email_pod_request": {
                "router": "pod_request_mark",
                "map": {"marked": "send_email_continue", "skipped_mark": "send_email_continue"},
            },
        },
    },
}
