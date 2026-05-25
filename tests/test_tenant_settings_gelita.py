"""Tests for Gelita typed tenant settings and registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.load_tendering_settings import (
    gelita_escalate_tender_settings,
    gelita_send_tender_email_settings,
    parse_gelita_tenant_settings,
)
from app.domain.tenant_settings import GelitaTenantSettings, parse_tenant_settings
from app.domain.tenant_settings.registry import normalize_tenant_settings_dict

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gelita_tenant_settings.json"


def _raw_settings() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_validates_as_gelita_tenant_settings() -> None:
    model = GelitaTenantSettings.model_validate(_raw_settings())
    assert model.email_webhook_name == "gelita"
    ftl = model.load_tendering.ftl.send_tender_email
    assert isinstance(ftl.vendor_email, list)
    assert len(ftl.vendor_email) >= 1
    assert ftl.vendor_cc == []
    assert ftl.vendor_bcc == []


def test_parse_tenant_settings_registry() -> None:
    parsed = parse_tenant_settings("gelita", _raw_settings())
    assert isinstance(parsed, GelitaTenantSettings)
    assert parse_tenant_settings("unknown-tenant", _raw_settings()) is None


def test_normalize_coerces_email_lists() -> None:
    raw = _raw_settings()
    raw["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"] = "solo@v.com"
    normalized = normalize_tenant_settings_dict("gelita", raw)
    vendor = normalized["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"]
    assert vendor == ["solo@v.com"]


def test_gelita_action_settings_helpers() -> None:
    data = {"tenant_settings": _raw_settings()}
    send = gelita_send_tender_email_settings(data, load_type="FTL")
    assert send is not None
    rec = send.recipients()
    assert rec.to
    esc = gelita_escalate_tender_settings(data, load_type="LTL")
    assert esc is not None
    assert esc.recipients().to


def test_invalid_vendor_email_rejected() -> None:
    raw = _raw_settings()
    raw["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"] = []
    with pytest.raises(ValidationError):
        parse_gelita_tenant_settings({"tenant_settings": raw})
