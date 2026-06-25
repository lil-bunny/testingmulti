"""Parse ``routing_guide`` JSON columns; tenant-agnostic shape validation."""

from __future__ import annotations

from typing import Any

from app.domain.routing_guide.types import PlanCarriers


def customer_aliases_from_value(value: Any) -> list[str]:
    """Parse ``customer_aliases`` JSON; used by ``RoutingGuideRepository`` on read."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_plan_carriers(value: Any) -> PlanCarriers:
    """Parse ``carriers`` JSON ``{slot: {name: email}, ...}`` for lookup and seed."""
    if not isinstance(value, dict):
        return {}
    out: PlanCarriers = {}
    for slot_key, raw_slot in value.items():
        slot = str(slot_key or "").strip()
        if not slot or not isinstance(raw_slot, dict):
            continue
        slot_map: dict[str, str] = {}
        for name, email in raw_slot.items():
            clean_name = str(name or "").strip()
            clean_email = str(email or "").strip()
            if clean_name and clean_email:
                slot_map[clean_name] = clean_email
        if slot_map:
            out[slot] = slot_map
    return out
