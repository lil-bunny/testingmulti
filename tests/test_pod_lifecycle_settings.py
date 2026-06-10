"""Tests for POD lifecycle tenant settings accessors."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.domain.pod_lifecycle_settings import (
    hydrate_pod_account_id,
    resolve_pod_sender_account_id,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_T3RA_SETTINGS = json.loads(
    (_REPO_ROOT / "scripts/t3ra_tenant_settings.json").read_text(encoding="utf-8")
)


def test_resolve_prefers_explicit_payload_account_id() -> None:
    data = {
        "account_id": "webhook-account",
        "tenant_settings": {"mikey_account_id": "tenant-account"},
    }
    assert resolve_pod_sender_account_id(data) == "webhook-account"


def test_resolve_uses_mikey_account_id_from_tenant_settings() -> None:
    data = {"tenant_settings": _T3RA_SETTINGS}
    assert resolve_pod_sender_account_id(data) == _T3RA_SETTINGS["mikey_account_id"]


def test_resolve_falls_back_to_env_when_tenant_missing() -> None:
    with patch("app.domain.pod_lifecycle_settings.settings.UNIPILE_ACCOUNT_ID", "env-account"):
        assert resolve_pod_sender_account_id({}) == "env-account"


def test_hydrate_sets_account_id_on_payload() -> None:
    payload = {"tenant_settings": _T3RA_SETTINGS}
    hydrate_pod_account_id(payload)
    assert payload["account_id"] == _T3RA_SETTINGS["mikey_account_id"]


def test_hydrate_does_not_override_existing_account_id() -> None:
    payload = {
        "account_id": "keep-me",
        "tenant_settings": _T3RA_SETTINGS,
    }
    hydrate_pod_account_id(payload)
    assert payload["account_id"] == "keep-me"


def test_resolve_from_workflow_state_object() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _T3RA_SETTINGS},
    )
    assert resolve_pod_sender_account_id(state) == _T3RA_SETTINGS["mikey_account_id"]
