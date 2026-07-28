"""Tests for T3raAppointmentSchedulingSettings recipient normalization."""

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


def test_legacy_flat_to_cc_bcc_normalizes_to_emails() -> None:
    cfg = T3raAppointmentSchedulingSettings.model_validate(
        {
            "to": ["primary@example.com"],
            "cc": ["ops@example.com"],
            "bcc": ["bcc@example.com"],
        }
    )
    assert cfg.emails.to == ["primary@example.com"]
    assert cfg.emails.cc == ["ops@example.com"]
    assert cfg.emails.bcc == ["bcc@example.com"]


def test_legacy_email_cc_normalizes_to_emails_cc() -> None:
    cfg = T3raAppointmentSchedulingSettings.model_validate(
        {"email_cc": ["legacy@example.com"]}
    )
    assert cfg.emails.cc == ["legacy@example.com"]
    assert cfg.emails.to == []
