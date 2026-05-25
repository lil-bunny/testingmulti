"""Tests for load-tendering settings accessors on workflow state / payload."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.domain.load_tendering_settings import (
    action_settings,
    load_tendering_settings_root,
)

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gelita_tenant_settings.json"


def _gelita_tenant_settings() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_action_settings_from_state_data() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    calc = action_settings(state, "tender_calculate")
    assert calc["pallet_weight_lbs"] == 45.0
    assert calc["pallet_threshold"] == 8
    assert calc["gelita_pickup_address"]["name"] == "GELITA USA"


def test_action_settings_from_payload_dict() -> None:
    payload = {"tenant_settings": _gelita_tenant_settings()}
    esc = action_settings(payload, "escalate_tender", load_type="LTL")
    assert esc["escalation_hours"] == 0.1
    assert "escalation_email_body" in esc


def test_missing_action_returns_empty_dict() -> None:
    state = SimpleNamespace(data={"tenant_settings": {}})
    assert action_settings(state, "tender_calculate") == {}
    assert load_tendering_settings_root(state) == {}


def test_ltl_and_ftl_buckets_from_fixture() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    ftl_email = action_settings(state, "send_tender_email", load_type="FTL")
    assert "{delivery_date}" in ftl_email["email_template_html"]
    assert "<!DOCTYPE html>" in ftl_email["email_template_html"]
    ftl_rem = action_settings(state, "send_tender_reminder", load_type="FTL")
    assert ftl_rem["reminder_1_hours"] == 24
    assert "<!DOCTYPE html>" in ftl_rem["reminder_body"]
    ftl_esc = action_settings(state, "escalate_tender", load_type="FTL")
    assert ftl_esc["escalation_hours"] == 28
    assert "FTL tender escalation" in ftl_esc["escalation_email_body"]
    assert "<!DOCTYPE html>" in ftl_esc["escalation_email_body"]
    ltl_email = action_settings(state, "send_tender_email", load_type="LTL")
    assert "<!DOCTYPE html>" in ltl_email["email_template_html"]
    ltl_esc = action_settings(state, "escalate_tender", load_type="LTL")
    assert "<!DOCTYPE html>" in ltl_esc["escalation_email_body"]
    ltl_rem = action_settings(state, "send_tender_reminder", load_type="LTL")
    assert "<!DOCTYPE html>" in ltl_rem["reminder_body"]


def test_shared_unipile_accounts_merged_from_tenant_settings_root() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    ltl_email = action_settings(state, "send_tender_email", load_type="LTL")
    assert ltl_email["ana_gelita_at_freightx_ai_account_id"] == "8Lu6Ht9vTyyN1Zdb1mVtPw"
    ltl_rem = action_settings(state, "send_tender_reminder", load_type="LTL")
    assert ltl_rem["ana_at_gelita_account_id"] == "8Lu6Ht9vTyyN1Zdb1mVtPw"
    ftl_esc = action_settings(state, "escalate_tender", load_type="FTL")
    assert ftl_esc["ana_at_gelita_account_id"] == "8Lu6Ht9vTyyN1Zdb1mVtPw"
    assert isinstance(ftl_esc["escalation_notify_email"], list)
    assert len(ftl_esc["escalation_notify_email"]) >= 1
    ftl_vendor = action_settings(state, "send_tender_email", load_type="FTL")
    assert isinstance(ftl_vendor["vendor_email"], list)
    assert "ana_at_gelita_account_id" not in _gelita_tenant_settings()["load_tendering"]["ftl"][
        "escalate_tender"
    ]


def test_delivery_locations_excel_action_from_fixture() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    dl = action_settings(state, "delivery_locations_excel")
    assert dl["delivery_locations_tab_name"] == "Delivery locations"
    assert dl["delivery_locations_max_rows"] == 50000
    assert str(dl["delivery_locations_share_url"]).startswith("https://")
