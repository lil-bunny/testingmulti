"""Tests for load-tendering settings accessors on workflow state / payload."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.load_tendering_settings import (
    action_settings,
    gelita_tender_calculate_settings,
    load_type_from_pallet_totals,
    load_tendering_settings_root,
)
from app.domain.tenant_settings.gelita import normalize_pallet_type_label
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _gelita_tenant_settings() -> dict:
    return load_tenant_settings_dev("gelita")


def test_action_settings_from_state_data() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    calc = action_settings(state, "tender_calculate")
    wood = calc["pallet_profiles"]["wood_4way"]
    assert wood["weight_lbs"] == 50.0
    assert wood["threshold"] == 8
    assert calc["gelita_pickup_address"]["name"] == "GELITA USA"


def test_action_settings_from_payload_dict() -> None:
    payload = {"tenant_settings": _gelita_tenant_settings()}
    esc = action_settings(payload, "escalate_tender", load_type="LTL")
    assert "LTL tender escalation" in esc["escalation_email_body"]
    assert esc["emails"]["to"]


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
    assert "Following up on the tender request" in ftl_rem["reminder_body"]
    assert "reminder_1_hours" not in ftl_rem
    ftl_esc = action_settings(state, "escalate_tender", load_type="FTL")
    assert "escalation_hours" not in ftl_esc
    assert "FTL tender escalation" in ftl_esc["escalation_email_body"]
    assert "<!DOCTYPE html>" in ftl_esc["escalation_email_body"]
    ltl_email = action_settings(state, "send_tender_email", load_type="LTL")
    assert "<!DOCTYPE html>" in ltl_email["email_template_html"]
    ltl_esc = action_settings(state, "escalate_tender", load_type="LTL")
    assert "<!DOCTYPE html>" in ltl_esc["escalation_email_body"]
    ltl_rem = action_settings(state, "send_tender_reminder", load_type="LTL")
    assert "Following up on the tender request" in ltl_rem["reminder_body"]


def test_shared_unipile_accounts_merged_from_tenant_settings_root() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    account_id = "oizK1OAzTyqJJJ6VySWEDw"
    ltl_email = action_settings(state, "send_tender_email", load_type="LTL")
    assert ltl_email["ana_at_gelita_account_id"] == account_id
    assert "ana_gelita_at_freightx_ai_account_id" not in ltl_email
    ltl_rem = action_settings(state, "send_tender_reminder", load_type="LTL")
    assert ltl_rem["ana_at_gelita_account_id"] == account_id
    ftl_esc = action_settings(state, "escalate_tender", load_type="FTL")
    assert ftl_esc["ana_at_gelita_account_id"] == account_id
    assert isinstance(ftl_esc["emails"]["to"], list)
    assert len(ftl_esc["emails"]["to"]) >= 1
    ftl_vendor = action_settings(state, "send_tender_email", load_type="FTL")
    assert isinstance(ftl_vendor["emails"]["to"], list)
    assert "ana_at_gelita_account_id" not in _gelita_tenant_settings()["load_tendering"]["ftl"][
        "escalate_tender"
    ]


def test_gelita_tender_calculate_resolves_pack_code_pallet_types() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    calc = gelita_tender_calculate_settings(state)
    assert calc is not None
    assert calc.resolve_pallet_type("4-way wood")[0] == "wood_4way"
    assert calc.resolve_pallet_type("4 way plastic")[0] == "plastic_4way"
    assert calc.resolve_pallet_type("European Pallet")[0] == "european"
    assert normalize_pallet_type_label("4-way plastic") == normalize_pallet_type_label(
        "4 way plastic"
    )


def test_gelita_tender_calculate_defaults_missing_pallet_type_to_wood_4way() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    calc = gelita_tender_calculate_settings(state)
    assert calc is not None
    assert calc.pallet_profiles["wood_4way"].default is True
    for missing in (None, "", "   "):
        key, profile = calc.resolve_pallet_type(missing)
        assert key == "wood_4way"
        assert profile.default is True
        assert profile.weight_lbs == 50.0
        assert profile.threshold == 8


def test_gelita_tender_calculate_defaults_unknown_pallet_type_to_wood_4way() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    calc = gelita_tender_calculate_settings(state)
    assert calc is not None
    key, profile = calc.resolve_pallet_type("unknown pallet type")
    assert key == "wood_4way"
    assert profile.weight_lbs == 50.0


def test_load_type_from_pallet_totals_buckets_by_profile_threshold() -> None:
    assert (
        load_type_from_pallet_totals(
            [
                {"pallets_count": 5, "pallet_profile": "wood_4way", "pallet_threshold": 8},
                {"pallets_count": 4, "pallet_profile": "european", "pallet_threshold": 6},
            ]
        )
        == "LTL"
    )
    assert (
        load_type_from_pallet_totals(
            [
                {"pallets_count": 5, "pallet_profile": "wood_4way", "pallet_threshold": 8},
                {"pallets_count": 7, "pallet_profile": "european", "pallet_threshold": 6},
            ]
        )
        == "FTL"
    )


def test_reminder_schedule_hours_only_under_load_tendering_reminders() -> None:
    root = _gelita_tenant_settings()["load_tendering"]
    ftl_steps = root["reminders"]["variants"]["ftl"]
    assert ftl_steps[0]["delay_hours"] == pytest.approx(0.016)
    assert ftl_steps[1]["event_type"] == "escalation_due"
    assert "reminder_1_hours" not in root["ftl"]["send_tender_reminder"]
    assert "escalation_hours" not in root["ftl"]["escalate_tender"]

