"""Tests for t3ra typed tenant settings (POD reminders)."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.prompt_step_keys import (
    POD_PAGE_EXTRACTION,
    POD_VS_RATECON_SUMMARY,
    RATECON_PAGE_EXTRACTION,
)
from app.domain.tenant_settings import parse_tenant_settings
from app.domain.tenant_settings.registry import normalize_tenant_settings_dict
from app.domain.tenant_settings.t3ra import T3raTenantSettings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_T3RA_SETTINGS = json.loads(
    (_REPO_ROOT / "scripts/tenant_settings/t3ra/t3ra.tenant_settings.dev.json").read_text(encoding="utf-8")
)


def test_t3ra_fixture_validates() -> None:
    model = T3raTenantSettings.model_validate(_T3RA_SETTINGS)
    assert model.inbound_routing_emails == ["deb@freightx.ai"]
    assert model.mikey_account_id == "W7Xyw8gLT2mvog37VsGHZQ"
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
    assert model.prompts[POD_PAGE_EXTRACTION] == "pod-page-extraction:staging"
    assert model.prompts[RATECON_PAGE_EXTRACTION] == "ratecon-page-extraction:staging"
    assert model.prompts[POD_VS_RATECON_SUMMARY] == "pod-vs-ratecon-summary:staging"
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
