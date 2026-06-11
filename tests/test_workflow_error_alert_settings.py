"""Tests for workflow_error_alerts settings resolution."""

from __future__ import annotations

from app.domain.workflow_error_alert_settings import resolve_workflow_error_alert_settings


def test_resolve_workflow_override_replaces_tenant_default() -> None:
    settings = resolve_workflow_error_alert_settings(
        {
            "tenant_settings": {
                "workflow_error_alerts": {
                    "enabled": True,
                    "channels": [
                        {
                            "channel": "email",
                            "to": ["default@example.com"],
                            "subject": "Default {error_code}",
                            "body_template": "<p>{failure_reason}</p>",
                        }
                    ],
                },
                "load_tendering": {
                    "workflow_error_alerts": {
                        "enabled": True,
                        "channels": [
                            {
                                "channel": "email",
                                "to": ["load@example.com"],
                                "subject": "Load {error_code}",
                                "body_template": "<p>{failure_reason}</p>",
                            }
                        ],
                    }
                },
            }
        },
        workflow_name="load_tendering",
    )
    assert settings is not None
    email = settings.channels[0]
    assert email.channel == "email"
    assert email.to == ["load@example.com"]
    assert email.subject == "Load {error_code}"


def test_resolve_falls_back_to_tenant_default() -> None:
    settings = resolve_workflow_error_alert_settings(
        {
            "tenant_settings": {
                "workflow_error_alerts": {
                    "enabled": True,
                    "channels": [
                        {
                            "channel": "email",
                            "to": ["default@example.com"],
                            "subject": "Default",
                            "body_template": "<p>x</p>",
                        }
                    ],
                },
                "load_tendering": {},
            }
        },
        workflow_name="load_tendering",
    )
    assert settings is not None
    assert settings.channels[0].to == ["default@example.com"]
