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
    esc = action_settings(payload, "escalate_tender")
    assert esc["escalation_hours"] == 0.1
    assert "escalation_email_body" in esc


def test_missing_action_returns_empty_dict() -> None:
    state = SimpleNamespace(data={"tenant_settings": {}})
    assert action_settings(state, "tender_calculate") == {}
    assert load_tendering_settings_root(state) == {}


def test_delivery_locations_excel_action_from_fixture() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _gelita_tenant_settings()},
    )
    dl = action_settings(state, "delivery_locations_excel")
    assert dl["delivery_locations_tab_name"] == "Delivery locations"
    assert dl["delivery_locations_max_rows"] == 50000
    assert str(dl["delivery_locations_share_url"]).startswith("https://")
