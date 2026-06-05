WORKFLOW_CONFIGS = {
    "pod_lifecycle": {
        "entry": "route_event",
        "exit": "end",
        "nodes": [
            "route_event",
            "get_shipment",
            "check_pod_request_triggered",
            "read_workflow_lifecycle",
            "check_existing_pod",
            "send_email",
            "record_and_schedule_pod_request",
            "record_pod_started_activity",
            "record_pod_reminder_activity",
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
            ["get_email_attachments", "ratecon_analysis"],
            ["ratecon_analysis","classify_attachments"],
            ["classify_attachments", "pod_analysis"],
            ["pod_analysis", "pod_vs_ratecon_analysis"],
            ["pod_vs_ratecon_analysis", "upload_to_turvo"],
            ["upload_to_turvo", "update_shipment"],
            ["update_shipment", "end"],
            ["send_email", "record_pod_reminder_activity"],
            ["record_pod_reminder_activity", "end"],
            ["record_and_schedule_pod_request", "record_pod_started_activity"],
            ["record_pod_started_activity", "end"],
        ],
        "routers": {
            "route_event": {
                "router": "event_type",
                "map": {
                    "route_completed": "check_pod_request_triggered",
                    "email_received": "read_workflow_lifecycle",
                    "reminder_due": "check_existing_pod",
                },
            },
            "check_pod_request_triggered": {
                "router": "pod_request_triggered_router",
                "map": {
                    "blocked": "end",
                    "continue": "get_shipment",
                },
            },
            "get_shipment": {
                "router": "shipment_router",
                # TODO: a common "missing" key instead of multiple keys mapping to same END node
                "map": {
                    "convoy": "end",
                    "non_convoy": "check_existing_pod",
                    # Pod reply workflow
                    "valid_shipment_status": "get_email_attachments",
                    "invalid_shipment_status": "end",
                },
            },
            "check_existing_pod": {
                "router": "pod_missing_dispatch",
                "map": {
                    "exists": "end",
                    "schedule_initial": "record_and_schedule_pod_request",  # no send_email on initial
                    "send_now": "send_email",  # reminder_due path
                    "skip_send": "end",
                },
            },
            "read_workflow_lifecycle": {
                "router": "read_workflow_lifecycle_router",
                "map": {"is_found": "get_shipment", "missing": "end"},
            }
        },
    },
    "ratecon": {
        "entry": "resolve_load_to_shipment",
        "exit": "end",
        "nodes": [
            "resolve_load_to_shipment",
            "get_shipment",
            "link_shipment_locations",
            "resolve_workflow_lifecycle",
            "record_ratecon_received_activity",
            "upload_ratecon_attachments",
            "record_ratecon_upload_activity",
            "ratecon_analysis",
            "record_ratecon_llm_activity",
            "record_ratecon_processed_activity",
            "check_ratecon_workflow_lifecycle",
            "end",
        ],
        "edges": [
            ["resolve_load_to_shipment", "get_shipment"],
            ["get_shipment", "link_shipment_locations"],
            ["link_shipment_locations", "resolve_workflow_lifecycle"],
            ["resolve_workflow_lifecycle", "record_ratecon_received_activity"],
            ["record_ratecon_received_activity", "upload_ratecon_attachments"],
            ["upload_ratecon_attachments", "record_ratecon_upload_activity"],
            ["record_ratecon_upload_activity", "ratecon_analysis"],
            ["ratecon_analysis", "record_ratecon_llm_activity"],
            ["record_ratecon_llm_activity", "record_ratecon_processed_activity"],
            ["record_ratecon_processed_activity", "check_ratecon_workflow_lifecycle"],
            ["check_ratecon_workflow_lifecycle", "end"],
        ],
        "routers": {},
    },
    "load_tendering": {
        "entry": "route_event",
        "exit": "end",
        "nodes": [
            "route_event",
            "record_tender_created_activity",
            "calculate_tender_params",
            "send_tender_email",
            "log_tender_activity",
            "record_tender_sent_to_carrier",
            "schedule_tender_reminders",
            "classify_carrier_ack",
            "record_ack_received",
            "read_tender_row",
            "send_tender_reminder",
            "update_reminder_status",
            "escalate_tender",
            "end",
        ],
        "edges": [
            ["record_tender_created_activity", "calculate_tender_params"],
            ["send_tender_email", "log_tender_activity"],
            ["log_tender_activity", "end"],
            ["record_tender_sent_to_carrier", "schedule_tender_reminders"],
            ["schedule_tender_reminders", "end"],
            ["record_ack_received", "end"],
            ["send_tender_reminder", "update_reminder_status"],
            ["update_reminder_status", "end"],
            ["escalate_tender", "end"],
        ],
        "routers": {
            "route_event": {
                "router": "event_type",
                "map": {
                    "tender_created": "record_tender_created_activity",
                    "carrier_email_received": "record_tender_sent_to_carrier",
                    "ack_received": "classify_carrier_ack",
                    "reminder_due": "read_tender_row",
                    "escalation_due": "read_tender_row",
                },
            },
            "calculate_tender_params": {
                "router": "load_type_router",
                "map": {
                    "ltl_path": "send_tender_email",
                    "ftl_path": "send_tender_email",
                    "error_path": "end",
                },
            },
            "read_tender_row": {
                "router": "tender_status_router",
                "map": {
                    "completed": "end",
                    "reminder_due": "send_tender_reminder",
                    "escalation_due": "escalate_tender",
                    "missing": "end",
                },
            },
            "classify_carrier_ack": {
                "router": "carrier_ack_router",
                "map": {
                    "accepted": "record_ack_received",
                    "rejected": "record_ack_received",
                    "do_nothing": "end",
                },
            },
        },
    },
}
