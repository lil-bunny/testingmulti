"""Small pure helpers for appointment scheduling."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def is_costco_customer(customer_name: str) -> bool:
    # Email parity with AgenticAI: detection is "costco" only. Pet Food Experts
    # gets the standard email layout, not Costco presentation.
    return "costco" in str(customer_name or "").lower()
