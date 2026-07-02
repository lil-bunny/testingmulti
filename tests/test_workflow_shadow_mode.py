"""Tests for workflow shadow mode tenant settings helpers."""

from __future__ import annotations

from app.domain.tenant_settings.email_recipients import EmailRecipients
from app.domain.tenant_settings.workflow_shadow_mode import (
    parse_shadow_mail_recipients,
    shadow_mail_metadata_patch,
    shadow_metadata_patch,
    workflow_shadow_active,
    workflow_shadow_mode_enabled,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def test_workflow_shadow_mode_enabled_reads_nested_block() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_mode"] = True
    assert workflow_shadow_mode_enabled(settings, workflow_name="driver_assignment") is True
    assert workflow_shadow_mode_enabled(settings, workflow_name="pod_lifecycle") is False


def test_workflow_shadow_mode_defaults_false() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert workflow_shadow_mode_enabled(settings, workflow_name="driver_assignment") is False


def test_workflow_shadow_active_uses_injected_state_flag() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert workflow_shadow_active(
        settings,
        {"workflow_shadow_mode": True},
        workflow_name="pod_lifecycle",
    ) is True


def test_shadow_metadata_patch() -> None:
    assert shadow_metadata_patch({}) == {}
    assert shadow_metadata_patch({"workflow_shadow_mode": True}) == {
        "workflow_shadow_mode": True
    }


def test_parse_shadow_mail_recipients_valid() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_emails"] = {"to": ["deb@freightx.ai"]}
    recipients = parse_shadow_mail_recipients(settings, workflow_name="driver_assignment")
    assert recipients is not None
    assert recipients.to == ["deb@freightx.ai"]


def test_parse_shadow_mail_recipients_missing_block() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert parse_shadow_mail_recipients(settings, workflow_name="driver_assignment") is None


def test_parse_shadow_mail_recipients_empty_to() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["pod_lifecycle"]["shadow_emails"] = {"to": []}
    assert parse_shadow_mail_recipients(settings, workflow_name="pod_lifecycle") is None


def test_parse_shadow_mail_recipients_invalid() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_emails"] = {"cc": ["only-cc@example.com"]}
    assert parse_shadow_mail_recipients(settings, workflow_name="driver_assignment") is None


def test_shadow_mail_metadata_patch() -> None:
    recipients = EmailRecipients(to=["deb@freightx.ai"])
    assert shadow_mail_metadata_patch(redirected=True, recipients=recipients) == {
        "shadow_mail_redirect": True,
        "shadow_mail_to": ["deb@freightx.ai"],
    }
    assert shadow_mail_metadata_patch(redirected=False, recipients=recipients) == {}
