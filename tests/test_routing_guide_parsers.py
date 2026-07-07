"""Unit tests for routing-guide carrier JSON parsing."""

from __future__ import annotations

from app.domain.routing_guide.parsers import normalize_plan_carriers
from app.domain.routing_guide.types import PlanCarrierSlot, plan_carriers_to_json


def test_normalize_plan_carriers_parses_name_email_slots() -> None:
    carriers = normalize_plan_carriers(
        {
            "a": {"name": "Schneider", "email": "carrier@example.com"},
            "b": {"name": "Axle", "email": "axle@example.com"},
        }
    )
    assert carriers == {
        "a": PlanCarrierSlot(name="Schneider", email="carrier@example.com"),
        "b": PlanCarrierSlot(name="Axle", email="axle@example.com"),
    }


def test_normalize_plan_carriers_strips_whitespace() -> None:
    carriers = normalize_plan_carriers(
        {"a": {"name": "  Schneider  ", "email": " carrier@example.com "}}
    )
    assert carriers["a"] == PlanCarrierSlot(
        name="Schneider",
        email="carrier@example.com",
    )


def test_normalize_plan_carriers_skips_empty_name_or_email() -> None:
    assert normalize_plan_carriers({"a": {"name": "", "email": "x@y.com"}}) == {}
    assert normalize_plan_carriers({"a": {"name": "Schneider", "email": ""}}) == {}


def test_normalize_plan_carriers_rejects_legacy_name_as_key_shape() -> None:
    assert normalize_plan_carriers(
        {"a": {"Schneider": "carrier@example.com"}}
    ) == {}


def test_normalize_plan_carriers_skips_extra_keys() -> None:
    assert normalize_plan_carriers(
        {"a": {"name": "Schneider", "email": "carrier@example.com", "phone": "555"}}
    ) == {}


def test_plan_carriers_to_json_round_trips_storage_shape() -> None:
    carriers = normalize_plan_carriers(
        {"a": {"name": "ONE", "email": "one@example.com"}}
    )
    assert plan_carriers_to_json(carriers) == {
        "a": {"name": "ONE", "email": "one@example.com"},
    }
