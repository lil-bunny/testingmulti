"""Parse ``routing_guide`` JSON columns; tenant-agnostic shape validation."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.routing_guide.types import PlanCarrierSlot, PlanCarriers


def customer_aliases_from_value(value: Any) -> list[str]:
    """Parse ``customer_aliases`` JSON; used by ``RoutingGuideRepository`` on read."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_plan_carriers(value: Any) -> PlanCarriers:
    """Parse ``carriers`` JSON ``{slot: {name, email}, ...}`` for lookup and seed."""
    if not isinstance(value, dict):
        return {}
    out: PlanCarriers = {}
    for slot_key, raw_slot in value.items():
        slot = str(slot_key or "").strip()
        if not slot or not isinstance(raw_slot, dict):
            continue
        try:
            parsed = PlanCarrierSlot.model_validate(raw_slot)
        except ValidationError:
            continue
        if parsed.name and parsed.email:
            out[slot] = parsed
    return out
