"""
Single precedence rules for ``shipment_id`` across POD / email workflow nodes.

* ``resolve_shipment_id`` — canonical Turvo id for S3 keys, ``documents`` rows,
  and analysis (cached ``shipment`` object wins when present).
* ``resolve_shipment_id_for_fetch`` — id used to call ``get_shipment``; ignores
  ``shipment`` so a stale dict cannot override correlation / payload.
"""

from __future__ import annotations

from typing import Any


def _strip_shipment_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_shipment_id_for_fetch(data: dict[str, Any]) -> str | None:
    """Resolve id for Turvo shipment fetch: correlation payload, then root ``shipment_id``."""
    payload = (data.get("workflow_correlation") or {}).get("payload") or {}
    sid = _strip_shipment_id(payload.get("shipment_id"))
    if sid:
        return sid
    sid = _strip_shipment_id(data.get("shipment_id"))
    if sid:
        return sid
    return None


def resolve_shipment_id(data: dict[str, Any]) -> str:
    """
    Canonical shipment id for attachment uploads, normalization, document rows,
    and extraction. Prefer Turvo-backed ``state['shipment']['shipment_id']``.
    """
    shipment = data.get("shipment")
    if isinstance(shipment, dict):
        sid = _strip_shipment_id(shipment.get("shipment_id"))
        if sid:
            return sid
    return resolve_shipment_id_for_fetch(data)
