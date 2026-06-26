"""Gelita routing-guide attempt counter and sub-status ladder."""

from __future__ import annotations

from typing import Any, Literal

from app.domain.gelita.routing_guide import GELITA_MAX_CARRIER_ATTEMPTS
from app.models.status import StatusSubType

GELITA_ROUTING_GUIDE_ATTEMPT_CEILING = GELITA_MAX_CARRIER_ATTEMPTS

ROUTING_GUIDE_ATTEMPT_METADATA_KEY = "routing_guide_attempt"

RoutingGuidePhase = Literal["tenant", "carrier"]

_TENANT_SUB_STATUS_BY_ATTEMPT: dict[int, StatusSubType] = {
    1: StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_1,
    2: StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_2,
    3: StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_3,
}

_CARRIER_SUB_STATUS_BY_ATTEMPT: dict[int, StatusSubType] = {
    1: StatusSubType.TENDER_SENT_TO_CARRIER_1,
    2: StatusSubType.TENDER_SENT_TO_CARRIER_2,
    3: StatusSubType.TENDER_SENT_TO_CARRIER_3,
}


def _parse_attempt(raw: Any) -> int | None:
    """Coerce a stored attempt counter; used by metadata and state readers."""
    try:
        attempt = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, attempt) if attempt >= 1 else None


def routing_guide_attempt_from_metadata(metadata: Any) -> int:
    """Read waterfall depth from ``workflow_lifecycles.metadata``."""
    if not isinstance(metadata, dict):
        return 1
    parsed = _parse_attempt(metadata.get(ROUTING_GUIDE_ATTEMPT_METADATA_KEY))
    return parsed if parsed is not None else 1


def routing_guide_has_attempt(metadata: Any) -> bool:
    """True when lifecycle metadata already stores a routing-guide attempt."""
    if not isinstance(metadata, dict):
        return False
    return ROUTING_GUIDE_ATTEMPT_METADATA_KEY in metadata


def sync_routing_guide_attempt_to_state(data: dict[str, Any], *, attempt: int) -> None:
    """Mirror lifecycle attempt into graph state for routers and reminder nodes."""
    data[ROUTING_GUIDE_ATTEMPT_METADATA_KEY] = max(1, int(attempt))


def routing_guide_attempt_from_state(data: dict[str, Any] | None) -> int:
    """Resolve waterfall attempt from graph state, then cached lifecycle metadata."""
    if not isinstance(data, dict):
        return 1
    parsed = _parse_attempt(data.get(ROUTING_GUIDE_ATTEMPT_METADATA_KEY))
    if parsed is not None:
        return parsed
    wl_meta = data.get("workflow_lifecycle_metadata")
    return routing_guide_attempt_from_metadata(wl_meta)


def gelita_routing_guide_sub_status_for(
    attempt: int,
    phase: RoutingGuidePhase,
) -> StatusSubType:
    """Map attempt + tenant/carrier phase to capped Gelita sub-status."""
    capped = min(max(int(attempt), 1), GELITA_ROUTING_GUIDE_ATTEMPT_CEILING)
    table = (
        _TENANT_SUB_STATUS_BY_ATTEMPT
        if phase == "tenant"
        else _CARRIER_SUB_STATUS_BY_ATTEMPT
    )
    return table[capped]
