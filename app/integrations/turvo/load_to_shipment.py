"""Resolve Turvo load/custom id to canonical shipment id via GET /v1/shipments/list."""

from __future__ import annotations

from typing import Any, Optional

from app.core.logger import get_logger
from app.integrations.turvo.public_api_client import TurvoApiClient

logger = get_logger(__name__)


def shipment_id_from_list_response(
    list_body: dict[str, Any],
    load_id: str,
    *,
    allow_single_row_without_custom_id: bool = True,
) -> str | None:
    """Parse Turvo ``/shipments/list`` JSON: first matching row's ``id`` (numeric shipment id)."""
    if not isinstance(list_body, dict):
        return None
    details = list_body.get("details", {}) or {}
    if not isinstance(details, dict):
        return None
    shipments = details.get("shipments", []) or []
    if not isinstance(shipments, list):
        return None
    lid = str(load_id).strip()
    for row in shipments:
        if not isinstance(row, dict):
            continue
        custom = row.get("customId")
        custom_s = str(custom).strip() if custom is not None else ""
        if allow_single_row_without_custom_id:
            if custom is not None and custom_s != lid:
                continue
        elif custom_s != lid:
            continue
        sid = row.get("id")
        if sid is not None and str(sid).strip():
            return str(sid)
    if (
        allow_single_row_without_custom_id
        and len(shipments) == 1
        and isinstance(shipments[0], dict)
    ):
        sid = shipments[0].get("id")
        if sid is not None and str(sid).strip():
            return str(sid)
    return None


async def load_id_to_shipment_id_async(
    tenant_slug: str,
    load_id: str,
    *,
    client: Optional[TurvoApiClient] = None,
) -> str | None:
    """Resolve load/custom id to Turvo shipment id (``id`` field from shipments list).

    Tries ``customId[eq]`` first. If that returns no match, falls back to an
    unfiltered ``/shipments/list`` call and matches ``customId`` client-side.
    """
    slug = (tenant_slug or "").strip()
    lid = str(load_id).strip() if load_id is not None else ""
    if not slug:
        raise ValueError("tenant_slug is required")
    if not lid:
        raise ValueError("load_id is required")

    api = client or TurvoApiClient()
    list_body = await api.request(
        slug,
        "GET",
        "/shipments/list",
        params={"customId[eq]": lid},
    )
    sid = shipment_id_from_list_response(list_body, lid)
    if sid:
        return sid

    logger.warning(
        "Turvo customId[eq] miss; falling back to unfiltered list tenant_slug=%s load_id=%s",
        slug,
        lid,
    )
    fallback_body = await api.request(slug, "GET", "/shipments/list")
    sid = shipment_id_from_list_response(
        fallback_body,
        lid,
        allow_single_row_without_custom_id=False,
    )
    if sid:
        logger.info(
            "Turvo customId fallback matched tenant_slug=%s load_id=%s shipment_id=%s",
            slug,
            lid,
            sid,
        )
    return sid
