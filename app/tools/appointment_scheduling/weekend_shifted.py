"""Pure helpers for weekend-shifted pickup scheduling."""

from __future__ import annotations

from typing import Any


def is_weekend_shifted_truthy(value: Any) -> bool:
    """Coerce LLM/UI weekend_shifted values to bool (Repo A compatible)."""
    if value is True:
        return True
    if value is None:
        return False
    try:
        normalized = str(value).strip().lower()
    except Exception:
        return False
    return normalized in ("true", "1", "yes", "y", "on")
