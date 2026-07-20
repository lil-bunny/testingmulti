"""Diamond / Ascend reference helpers for appointment scheduling."""

from __future__ import annotations

import re
from typing import Any

_OFFICE_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z-]*)")
_ASCEND_OFFICE_REFERENCE_PREFIX = "DIAMOND-"


def is_diamond_scheduling_reference(reference_number: Any) -> bool:
    """True when reference is non-empty and starts with DIAMOND (case-insensitive)."""
    ref = str(reference_number or "").strip()
    return bool(ref) and ref.upper().startswith("DIAMOND")


def ascend_office_code_from_reference(
    reference_number: str | None = None,
    shipment_number: str | None = None,
) -> str:
    """Ascend ``Office-Code`` from DIAMOND- prefixed reference or shipment number."""
    prefix = _ASCEND_OFFICE_REFERENCE_PREFIX.upper()
    for value in (reference_number, shipment_number):
        if value is None:
            continue
        s = str(value).strip()
        if not s or not s.upper().startswith(prefix):
            continue
        match = _OFFICE_PREFIX_RE.match(s)
        if match:
            code = match.group(1).rstrip("-")
            if code:
                return code
    return ""