"""Tests for T3raAppointmentSchedulingSettings."""

from __future__ import annotations

from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings


def test_nested_emails_shape() -> None:
    cfg = T3raAppointmentSchedulingSettings.model_validate(
        {
            "appointment_data_source": "/tmp/x.xlsx",
            "emails": {
                "to": [],
                "cc": ["ops@example.com"],
                "bcc": [],
            },
        }
    )
    assert cfg.emails.cc == ["ops@example.com"]
    assert cfg.emails.to == []


def test_cc_only_emails_without_to_key() -> None:
    cfg = T3raAppointmentSchedulingSettings.model_validate(
        {
            "emails": {"cc": ["ops@example.com"]},
        }
    )
    assert cfg.emails.cc == ["ops@example.com"]
    assert cfg.emails.to == []
