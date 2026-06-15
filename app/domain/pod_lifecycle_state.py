"""``state.data`` accessors and tool-failure helpers for the pod_lifecycle workflow."""

from __future__ import annotations

from typing import Any

from app.domain.error_catalog import ErrorCode, SystemError
from app.exceptions import WorkflowException
from app.workflows.shipment_resolver import resolve_shipment_id


def shipment_id_from_data(data: dict[str, Any]) -> str | None:
    """
    Canonical Turvo shipment id from workflow state.

    Delegates to the shared ``resolve_shipment_id`` so precedence rules are in
    one place: cached ``state['shipment']['shipment_id']`` wins, then lifecycle
    data, then root ``shipment_id``.
    """
    return resolve_shipment_id(data)


def load_id_from_data(data: dict[str, Any]) -> str:
    """Return ``load_id`` from workflow state, empty string when absent."""
    return str(data.get("load_id") or "").strip()


def raise_for_pod_tool_failure(
    result: dict[str, Any],
    error_map: dict[str, ErrorCode],
) -> None:
    """
    Raise ``WorkflowException`` for hard tool failures.

    Rules:
    - ``skipped=True`` is always treated as an intentional no-op; never raises.
    - ``success=False`` without ``skipped`` is a hard failure.
    - The ``error`` string in the result is looked up in ``error_map``; if not
      found, falls back to ``SystemError.UNEXPECTED_NODE_FAILURE``.
    - ``success=True`` (even with ``skipped``) passes through silently.
    """
    if result.get("skipped"):
        return
    if result.get("success"):
        return
    error_key = str(result.get("error") or "").strip()
    catalog_code: ErrorCode = error_map.get(error_key, SystemError.UNEXPECTED_NODE_FAILURE)
    raise WorkflowException(catalog_code)
