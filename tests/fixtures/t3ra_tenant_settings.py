"""Synthetic t3ra ``tenants.settings`` for unit tests (no credentials)."""

from __future__ import annotations

from typing import Any

T3RA_PROMPTS: dict[str, Any] = {
    "pod_lifecycle": {
        "page_extraction": "pod-page-extraction:staging",
        "vs_ratecon_summary": "pod-vs-ratecon-summary:staging",
        "vs_ratecon_semantic_match": "pod-vs-ratecon-semantic-match:staging",
        "attachment_classifier": "pod-attachment-classifier:staging",
    },
    "ratecon": {
        "page_extraction": "ratecon-page-extraction:staging",
    },
    "driver_assignment": {
        "driver_details": "driver-details-extract:staging",
    },
}


def minimal_t3ra_tenant_settings() -> dict[str, Any]:
    """Minimal settings dict that validates as ``T3raTenantSettings``."""
    return {
        "tms": {
            "provider": "turvo",
            "public_api_url": "https://example.invalid/turvo",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "x_api_key": "test-x-api-key",
        },
        "driver_assignment": {
            "reminders": {
                "steps": [
                    {"step": 1, "event_type": "reminder_due", "delay_hours": 0.16666666666666666},
                    {"step": 2, "event_type": "reminder_due", "delay_hours": 0.1},
                    {"step": 3, "event_type": "reminder_due", "delay_hours": 0.06666666666666667},
                    {"step": 4, "event_type": "reminder_due", "delay_hours": 0.03333333333333333},
                    {"step": 5, "event_type": "escalation_due", "delay_hours": 0.016666666666666666},
                ],
                "min_gap_hours": 3,
                "email_template_html": "<html>driver-reminder</html>",
            },
            "confirmation_email": {
                "tracking_customer_names": ["USCS CSC"],
                "tracking_template_html": "<html>tracking</html>",
                "default_template_html": "<html>default</html>",
                "send_invite_for_tracking": False,
                "send_invite_for_default": True,
            },
            "escalate_driver": {
                "teams_webhook_url": "https://example.invalid/webhook",
                "message_title": "Driver details missing — Load {load_id}",
            },
        },
        "pod_lifecycle": {
            "reminders": {
                "steps": [
                    {"step": 1, "event_type": "reminder_due", "delay_hours": 0.03333333333333333},
                    {"step": 2, "event_type": "reminder_due", "delay_hours": 0.06666666666666667},
                    {"step": 3, "event_type": "reminder_due", "delay_hours": 0.09666666666666666},
                ],
                "expire_grace_hours": 2,
                "email_template_html": "<html>pod-reminder</html>",
            },
        },
        "enabledProcesses": ["pod_lifecycle", "pod_collection", "driver_assignment"],
        "prompts": T3RA_PROMPTS,
        "mikey_account_id": {
            "account_id": "test-mikey-account-id",
            "email_alias": "ops@example.com",
        },
        "inbound_routing_emails": ["test@example.com"],
    }
