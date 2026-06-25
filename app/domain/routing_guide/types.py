"""Shared ``routing_guide`` table row shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PlanCarriers = dict[str, dict[str, str]]


@dataclass(frozen=True)
class RoutingGuideRow:
    id: str
    customer_name: str
    zipcode: str
    metadata: dict[str, Any]
    customer_aliases: list[str]
    carriers: PlanCarriers
