"""Shared thread → shipment context resolution for Unipile email ingress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ThreadShipmentContext:
    shipments_row_id: str
    shipment_number: str
    pod_lifecycle_id: str | None = None


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def resolve_primary_shipment_from_thread_rows(
    thread_context_rows: list[dict[str, Any]],
    *,
    pod_workflow_name: str,
) -> ThreadShipmentContext | None:
    """Pick the primary shipment on a thread (first row), with optional pod lifecycle id."""
    if not thread_context_rows:
        return None

    distinct_shipments = {
        _clean_string(row.get("shipments_row_id"))
        for row in thread_context_rows
        if _clean_string(row.get("shipments_row_id"))
    }
    if len(distinct_shipments) > 1:
        logger.warning(
            "unipile email thread: multiple shipments on thread shipments=%s",
            sorted(distinct_shipments),
        )

    primary_row = thread_context_rows[0]
    shipments_row_id = _clean_string(primary_row.get("shipments_row_id"))
    shipment_number = _clean_string(primary_row.get("shipment_number"))
    if not shipments_row_id or not shipment_number:
        return None

    pod_lifecycle_id: str | None = None
    for row in thread_context_rows:
        if _clean_string(row.get("shipments_row_id")) != shipments_row_id:
            continue
        if _clean_string(row.get("workflow_name")) == pod_workflow_name:
            pod_lifecycle_id = _clean_string(row.get("lifecycle_id"))
            break

    return ThreadShipmentContext(
        shipments_row_id=shipments_row_id,
        shipment_number=shipment_number,
        pod_lifecycle_id=pod_lifecycle_id,
    )
