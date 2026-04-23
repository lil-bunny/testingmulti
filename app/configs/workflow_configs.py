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
                "router": "convoy",
                "map": {
                    "convoy": "end",
                    "non_convoy": "read_workflow_correlation",
                },
            },
            "check_existing_pod": {
                "router": "pod_exists",
                "map": {"exists": "end", "missing": "send_email"},
            },
            "classify_inbound_email": {
                "router": "pod_reply",
                "map": {"is_reply": "update_workflow_correlation", "ignore": "end"},
            },
            "process_pod": {
                "router": "pod_exists",
                "map": {"exists": "update_shipment", "missing": "send_email"},
            },
        },
    },
}