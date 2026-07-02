"""Paths and loaders for tenant settings test fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TENANT_SETTINGS_DIR = _REPO_ROOT / "scripts" / "tenant_settings"


def tenant_settings_dev_path(slug: str) -> Path:
    return _TENANT_SETTINGS_DIR / slug / f"{slug}.tenant_settings.dev.json"


def load_tenant_settings_dev(slug: str) -> dict:
    normalized = (slug or "").strip().lower()
    if normalized == "t3ra":
        return minimal_t3ra_tenant_settings()
    return json.loads(tenant_settings_dev_path(slug).read_text(encoding="utf-8"))
