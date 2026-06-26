"""Shared ``routing_guide`` table row shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

PlanCarriers = dict[str, "PlanCarrierSlot"]


class PlanCarrierSlot(BaseModel):
    """One waterfall carrier for a plan slot (``a`` / ``b`` / ``c``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    email: str

    @field_validator("name", "email", mode="before")
    @classmethod
    def _strip_non_empty_strings(cls, value: Any) -> str:
        return str(value or "").strip()


@dataclass(frozen=True)
class RoutingGuideRow:
    id: str
    customer_name: str
    zipcode: str
    metadata: dict[str, Any]
    customer_aliases: list[str]
    carriers: PlanCarriers


def plan_carriers_to_json(carriers: PlanCarriers) -> dict[str, dict[str, str]]:
    """Serialize validated carriers for ``routing_guide.carriers`` JSONB storage."""
    return {slot: carrier.model_dump() for slot, carrier in carriers.items()}
