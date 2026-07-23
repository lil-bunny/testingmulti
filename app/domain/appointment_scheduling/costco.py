"""Costco appointment scheduling constants and detection."""

from __future__ import annotations

COSTCO_PROPOSED_DELIVERY_WALL_TIME = "06:00"


def is_costco_customer(customer_name: str) -> bool:
    # Email parity with AgenticAI: detection is "costco" only. Pet Food Experts
    # gets the standard email layout, not Costco presentation.
    return "costco" in str(customer_name or "").lower()
