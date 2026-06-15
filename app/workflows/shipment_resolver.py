"""
Single precedence rules for ``shipment_id`` across POD / email workflow nodes.

* ``resolve_shipment_id`` — canonical Turvo id for S3 keys and Turvo API calls
  (cached ``shipment`` object wins when present).
* ``resolve_shipments_row_id_for_db`` — ``shipments.id`` UUID for Postgres FK
  writes on ``documents`` and ``document_analysis``.
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
    """Resolve id for Turvo shipment fetch: lifecycle data, then root ``shipment_id``."""
    lifecycle = data.get("workflow_lifecycle") or {}
    sid = _strip_shipment_id(lifecycle.get("shipment_id"))
    if sid:
        return sid
    sid = _strip_shipment_id(data.get("shipment_id"))
    if sid:
        return sid
    return None


def resolve_shipment_id(data: dict[str, Any]) -> str | None:
    """
    Canonical Turvo shipment number for S3 object keys and external API calls.
    Prefer Turvo-backed ``state['shipment']['shipment_id']``.
    """
    shipment = data.get("shipment")
    if isinstance(shipment, dict):
        sid = _strip_shipment_id(shipment.get("shipment_id"))
        if sid:
            return sid
    return resolve_shipment_id_for_fetch(data)


def resolve_shipments_row_id_for_db(data: dict[str, Any]) -> str | None:
    """``shipments.id`` UUID for ``documents`` / ``document_analysis`` FK writes."""
    from app.services.workflow_lifecycle_service import WorkflowLifecycleService

    row_id = WorkflowLifecycleService._extract_db_shipment_id(data)
    if row_id:
        return row_id

    tenant_id = _strip_shipment_id(data.get("tenant_id"))
    if not tenant_id:
        return None
    return WorkflowLifecycleService().resolve_shipments_row_id(
        tenant_id=tenant_id,
        payload=data,
    )
