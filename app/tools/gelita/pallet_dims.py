"""Gelita pallet dimension helpers (partial single-pallet height scaling)."""

from __future__ import annotations

import re
from decimal import ROUND_FLOOR, Decimal
from typing import Any

_DIM_NUMBER = re.compile(r"[\d.]+")


def _parse_dim_triplet(value: str) -> tuple[Decimal, Decimal, Decimal] | None:
    parts = _DIM_NUMBER.findall(str(value or "").strip())
    if len(parts) < 3:
        return None
    try:
        return Decimal(parts[0]), Decimal(parts[1]), Decimal(parts[2])
    except Exception:
        return None


def _format_dim_value(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".")


def _format_dim_triplet(width: Decimal, depth: Decimal, height: Decimal) -> str:
    return (
        f'{_format_dim_value(width)}"'
        f'x{_format_dim_value(depth)}"'
        f'x{_format_dim_value(height)}"'
    )


def _positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(Decimal(str(value)))
    except Exception:
        return None
    return parsed if parsed > 0 else None


def adjust_unit_dims_for_partial_pallet(
    *,
    unit_dims: str,
    pallet_dims: str,
    pieces_count: int,
    pallets_count: int,
    units_per_pallet: Any,
) -> str:
    """Scale loaded-pallet height when one partial pallet has fewer bags than a full load.

    Keeps width/depth from ``unit_dims``. Height = pallet base + proportional bag stack:
    ``pallet_base + (full_height - pallet_base) * pieces / units_per_pallet``.

    Returns ``unit_dims`` unchanged when adjustment does not apply or inputs are invalid.
    """
    original = str(unit_dims or "").strip()
    if not original:
        return original
    if pallets_count != 1:
        return original

    full_bags = _positive_int(units_per_pallet)
    if full_bags is None or pieces_count <= 0 or pieces_count >= full_bags:
        return original

    loaded = _parse_dim_triplet(original)
    base = _parse_dim_triplet(str(pallet_dims or "").strip())
    if loaded is None or base is None:
        return original

    load_w, load_d, full_height = loaded
    _base_w, _base_d, base_height = base
    stack_height = full_height - base_height
    if stack_height <= 0:
        return original

    ratio = Decimal(pieces_count) / Decimal(full_bags)
    adjusted_height = base_height + (stack_height * ratio)
    rounded_height = adjusted_height.to_integral_value(rounding=ROUND_FLOOR)
    return _format_dim_triplet(load_w, load_d, rounded_height)
