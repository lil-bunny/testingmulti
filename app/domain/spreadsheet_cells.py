"""Normalize spreadsheet cell values that pandas reads as floats (e.g. order numbers)."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

_TRAILING_ZEROS_DECIMAL = re.compile(r"^(\d+)\.0+$")


def clean_cell_value(value: Any) -> Any:
    """Strip padding, collapse whitespace, and normalize missing cells to ``None``.

    pandas hands blank xlsx cells back as ``float('nan')``; without this, the
    NaN floats end up in ``delivery_address`` as the literal string ``"nan"``
    once they pass through ``str(...)``.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned or cleaned.lower() == "nan":
            return None
        return cleaned
    return value


def identifier_string_from_cell(value: Any) -> str | None:
    """
    Coerce an Excel cell to a stable identifier string.

    Whole-number floats (``93384.0``) become ``"93384"`` so ``str(float)`` does not
  leave a spurious ``.0`` suffix. Non-integer floats and arbitrary text are preserved.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value == int(value):
            return str(int(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        if value == value.to_integral_value():
            return str(int(value))
        return str(value).strip() or None

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    match = _TRAILING_ZEROS_DECIMAL.match(text)
    if match:
        return match.group(1)
    return text
