"""Tests for t3ra typed tenant settings (POD reminders)."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.tenant_settings import parse_tenant_settings
from app.domain.tenant_settings.t3ra import T3raTenantSettings

_FIXTURE = Path(__file__).resolve().parents[1] / "scripts" / "t3ra_tenant_settings.json"


def test_t3ra_fixture_validates() -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    model = T3raTenantSettings.model_validate(raw)
    assert len(model.pod_lifecycle.reminders.steps) == 3
    parsed = parse_tenant_settings("t3ra", raw)
    assert isinstance(parsed, T3raTenantSettings)
