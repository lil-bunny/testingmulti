"""Costco appointment scheduling constants and detection."""

from __future__ import annotations

COSTCO_PROPOSED_DELIVERY_WALL_TIME = "06:00"


def is_costco_customer(customer_name: str) -> bool:
    name = str(customer_name or "").lower()
    return "costco" in name or "pet food experts" in name
