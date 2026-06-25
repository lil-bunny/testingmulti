"""Gelita routing-guide attempt counter and sub-status ladder."""

from __future__ import annotations

from typing import Any, Literal

from app.domain.gelita.routing_guide import GELITA_MAX_CARRIER_ATTEMPTS
from app.models.status import StatusSubType

GELITA_ROUTING_GUIDE_ATTEMPT_CEILING = GELITA_MAX_CARRIER_ATTEMPTS

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


def _routing_guide_block(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    ftl = metadata.get("ftl")
    if not isinstance(ftl, dict):
        return {}
    routing_guide = ftl.get("routing_guide")
    if not isinstance(routing_guide, dict):
        return {}
    return routing_guide


def gelita_current_routing_guide_attempt(tender: dict[str, Any] | None) -> int:
    if not tender:
        return 1
    raw = _routing_guide_block(tender.get("metadata")).get("attempt")
    try:
        attempt = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, attempt)


def gelita_has_routing_guide_attempt(tender: dict[str, Any] | None) -> bool:
    if not tender:
        return False
    return "attempt" in _routing_guide_block(tender.get("metadata"))


def gelita_routing_guide_sub_status_for(
    attempt: int,
    phase: RoutingGuidePhase,
) -> StatusSubType:
    capped = min(max(int(attempt), 1), GELITA_ROUTING_GUIDE_ATTEMPT_CEILING)
    table = (
        _TENANT_SUB_STATUS_BY_ATTEMPT
        if phase == "tenant"
        else _CARRIER_SUB_STATUS_BY_ATTEMPT
    )
    return table[capped]
