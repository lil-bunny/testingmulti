"""Tests for t3ra typed tenant settings (POD reminders)."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.tenant_settings import parse_tenant_settings
from app.domain.tenant_settings.t3ra import T3raTenantSettings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_T3RA_SETTINGS = json.loads(
    (_REPO_ROOT / "scripts/tenant_settings/t3ra/t3ra.tenant_settings.dev.json").read_text(encoding="utf-8")
)


def test_t3ra_fixture_validates() -> None:
    model = T3raTenantSettings.model_validate(_T3RA_SETTINGS)
    assert model.inbound_routing_emails == ["ayushkansal303+fxratecon@gmail.com"]
    assert model.mikey_account_id == "7jKV_5jBQVG8med4nvXHJw"
    assert len(model.pod_lifecycle.reminders.steps) == 3
    assert model.prompts.pod_lifecycle.page_extraction == "pod-page-extraction:staging"
    assert model.prompts.ratecon.page_extraction == "ratecon-page-extraction:staging"
    assert model.prompts.pod_lifecycle.vs_ratecon_summary == "pod-vs-ratecon-summary:staging"
    parsed = parse_tenant_settings("t3ra", _T3RA_SETTINGS)
    assert isinstance(parsed, T3raTenantSettings)
