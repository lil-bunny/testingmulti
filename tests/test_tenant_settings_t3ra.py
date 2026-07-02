"""Tests for t3ra typed tenant settings (POD reminders)."""

from __future__ import annotations

from app.domain.tenant_settings import parse_tenant_settings
from app.domain.tenant_settings.registry import normalize_tenant_settings_dict
from app.domain.tenant_settings.t3ra import T3raTenantSettings
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_T3RA_SETTINGS = minimal_t3ra_tenant_settings()


def test_t3ra_fixture_validates() -> None:
    model = T3raTenantSettings.model_validate(_T3RA_SETTINGS)
    assert model.inbound_routing_emails == ["test@example.com"]
    assert model.mikey_account_id == "test-mikey-account-id"
    assert "driver_assignment" in model.enabledProcesses
    assert model.driver_assignment is not None
    assert model.driver_assignment.reminders.schedule_mode == "before_pickup"
    da_steps = model.driver_assignment.reminders.steps
    assert da_steps is not None
    assert len(da_steps) == 5
    assert da_steps[-1].event_type == "escalation_due"
    assert model.driver_assignment.escalate_driver is not None
    assert model.driver_assignment.escalate_driver.teams_webhook_url
    conf = model.driver_assignment.confirmation_email
    assert conf is not None
    assert conf.tracking_customer_names == ["USCS CSC"]
    assert conf.tracking_template_html
    assert conf.default_template_html
    assert len(model.pod_lifecycle.reminders.steps) == 3
    assert model.prompts.pod_lifecycle.page_extraction == "pod-page-extraction:staging"
    assert model.prompts.ratecon.page_extraction == "ratecon-page-extraction:staging"
    assert model.prompts.pod_lifecycle.vs_ratecon_summary == "pod-vs-ratecon-summary:staging"
    assert model.prompts.driver_assignment is not None
    assert model.prompts.driver_assignment.driver_details == "driver-details-extract:staging"
    parsed = parse_tenant_settings("t3ra", _T3RA_SETTINGS)
    assert isinstance(parsed, T3raTenantSettings)


def test_normalize_preserves_driver_assignment_settings() -> None:
    normalized = normalize_tenant_settings_dict("t3ra", _T3RA_SETTINGS)
    assert "driver_assignment" in normalized["enabledProcesses"]
    assert normalized["driver_assignment"]["reminders"]["schedule_mode"] == "before_pickup"
    conf = normalized["driver_assignment"]["confirmation_email"]
    assert conf["tracking_customer_names"] == ["USCS CSC"]
    assert conf["tracking_template_html"]
    assert conf["default_template_html"]
