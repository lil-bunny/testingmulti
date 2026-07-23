"""Boundary string normalization for appointment scheduling ingress and hydration."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()
