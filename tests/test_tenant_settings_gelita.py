"""Tests for Gelita typed tenant settings and registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.load_tendering_settings import (
    gelita_escalate_tender_settings,
    gelita_send_tender_email_settings,
    parse_gelita_tenant_settings,
)
from app.domain.prompt_step_keys import LOAD_TENDERING_CARRIER_ACK
from app.domain.tenant_settings import GelitaTenantSettings, parse_tenant_settings
from app.domain.tenant_settings.registry import normalize_tenant_settings_dict
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _raw_settings() -> dict:
    return load_tenant_settings_dev("gelita")


def test_fixture_validates_as_gelita_tenant_settings() -> None:
    model = GelitaTenantSettings.model_validate(_raw_settings())
    assert model.email_webhook_name == "gelita"
    assert model.prompts[LOAD_TENDERING_CARRIER_ACK].startswith(
        "carrier-ack-classify"
    )
    ftl = model.load_tendering.ftl.send_tender_email
    ltl = model.load_tendering.ltl.send_tender_email
    assert isinstance(ftl.vendor_email, list)
    assert len(ftl.vendor_email) >= 1
    assert ftl.vendor_cc == []
    assert ftl.vendor_bcc == []
    assert ftl.email_subject == ltl.email_subject
    assert "PICK UP REQUEST" in ftl.email_subject


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


def test_missing_carrier_ack_prompt_rejected() -> None:
    raw = _raw_settings()
    raw["prompts"] = {}
    with pytest.raises(ValidationError):
        GelitaTenantSettings.model_validate(raw)
