"""Tests for t3ra typed tenant settings (POD reminders)."""

from __future__ import annotations

from app.domain.tenant_settings import parse_tenant_settings
from app.domain.tenant_settings.t3ra import T3raTenantSettings
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def test_t3ra_fixture_validates() -> None:
    raw = load_tenant_settings_dev("t3ra")
    model = T3raTenantSettings.model_validate(raw)
    assert len(model.pod_lifecycle.reminders.steps) == 3
    parsed = parse_tenant_settings("t3ra", raw)
    assert isinstance(parsed, T3raTenantSettings)
