"""Tests for per-tenant TMS settings resolution."""

from __future__ import annotations

import pytest

from app.domain.tenant_settings.tms import (
    has_tms_partner_config,
    merge_tms_config,
    resolve_tms_settings,
)


def test_resolve_tms_settings_from_nested_block():
    cfg = {
        "inbound_routing_emails": ["ops@t3ra.test"],
        "tms": {
            "provider": "turvo",
            "public_api_url": "https://sandbox.turvo.com",
            "client_id": "cid",
            "client_secret": "csec",
            "x_api_key": "xkey",
            "user_name": "u@example.com",
        },
    }
    tms = resolve_tms_settings("t3ra", cfg)
    assert tms.public_api_url == "https://sandbox.turvo.com"
    assert tms.x_api_key == "xkey"
    assert tms.user_name == "u@example.com"


def test_merge_tms_config_legacy_flat_auth_fallback():
    cfg = {
        "user_name": "legacy@example.com",
        "password_ciphertext": "plain:pw",
        "access_token": "tok",
        "tms": {
            "provider": "turvo",
            "public_api_url": "https://sandbox.turvo.com",
            "client_id": "cid",
            "client_secret": "csec",
            "x_api_key": "xkey",
        },
    }
    merged = merge_tms_config(cfg)
    assert merged["user_name"] == "legacy@example.com"
    assert merged["access_token"] == "tok"


def test_resolve_tms_settings_raises_when_partner_fields_missing():
    cfg = {
        "tms": {
            "provider": "turvo",
            "user_name": "u@example.com",
        }
    }
    with pytest.raises(ValueError, match="missing required tenants.settings.tms fields"):
        resolve_tms_settings("t3ra", cfg)


def test_has_tms_partner_config_false_without_partner_fields():
    assert has_tms_partner_config({"tms": {"provider": "turvo"}}) is False
