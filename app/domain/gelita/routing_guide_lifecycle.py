"""Gelita routing-guide attempt counter and sub-status ladder."""

from __future__ import annotations

from typing import Any, Literal

from app.domain.gelita.routing_guide import GELITA_MAX_CARRIER_ATTEMPTS
from app.models.status import StatusSubType

GELITA_ROUTING_GUIDE_ATTEMPT_CEILING = GELITA_MAX_CARRIER_ATTEMPTS

ROUTING_GUIDE_ATTEMPT_METADATA_KEY = "routing_guide_attempt"
REMINDERS_SCHEDULED_FOR_ATTEMPT_KEY = "reminders_scheduled_for_attempt"

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


def optional_routing_guide_attempt(raw: Any) -> int | None:
    """Parse attempt from webhook or Celery payload; ``None`` when absent or invalid."""
    if raw is None:
        return None
    return _parse_attempt(raw)


def mark_stale_routing_guide_reminder_if_needed(
    *,
    data: dict[str, Any],
    event_type: str,
    payload_attempt: Any,
    lifecycle_metadata: Any,
    is_ftl: bool,
) -> bool:
    """
    Set ``stale_routing_guide_reminder`` when an FTL reminder payload is behind live attempt.

    Returns ``True`` when the flag was set (caller should stop graph work for this run).
    """
    if event_type not in ("reminder_due", "escalation_due"):
        return False
    if payload_attempt is None or not is_ftl:
        return False
    live_attempt = routing_guide_attempt_from_metadata(lifecycle_metadata)
    if not routing_guide_attempt_is_stale(payload_attempt, live_attempt):
        return False
    data["stale_routing_guide_reminder"] = True
    return True


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


def routing_guide_attempt_is_stale(
    payload_attempt: Any,
    live_attempt: Any,
) -> bool:
    """True when a scheduled Celery payload attempt differs from the live lifecycle attempt."""
    payload = _parse_attempt(payload_attempt)
    live = _parse_attempt(live_attempt)
    if payload is None or live is None:
        return False
    return payload != live


def routing_guide_thread_is_retired(
    thread_attempt: Any,
    live_attempt: Any,
) -> bool:
    """True when an inbound thread belongs to a prior routing-guide attempt."""
    thread = _parse_attempt(thread_attempt)
    live = _parse_attempt(live_attempt)
    if thread is None or live is None:
        return False
    return thread < live


def routing_guide_same_attempt_thread_conflict(
    *,
    linked_thread: str | None,
    incoming_thread: str,
) -> bool:
    """True when this attempt already has a different carrier thread linked."""
    linked = str(linked_thread or "").strip()
    incoming = str(incoming_thread or "").strip()
    if not linked or not incoming:
        return False
    return linked != incoming


def routing_guide_order_matches_lifecycle(
    resolved_tender_id: Any,
    lifecycle_tender_id: Any,
) -> bool:
    """True when ingress tender id matches the lifecycle's bound tender (order rollover guard)."""
    return str(resolved_tender_id or "").strip() == str(lifecycle_tender_id or "").strip()


def routing_guide_reminders_scheduled_for_attempt(
    metadata: Any,
    attempt: int,
) -> bool:
    """True when lifecycle metadata records reminders already scheduled for this attempt."""
    if not isinstance(metadata, dict):
        return False
    try:
        scheduled = int(metadata.get(REMINDERS_SCHEDULED_FOR_ATTEMPT_KEY))
        return scheduled == int(attempt)
    except (TypeError, ValueError):
        return False


def mark_routing_guide_reminders_scheduled_for_attempt(
    *,
    attempt: int,
) -> dict[str, int]:
    """Metadata patch marking per-attempt reminder schedule idempotency; used by lifecycle service."""
    return {REMINDERS_SCHEDULED_FOR_ATTEMPT_KEY: max(1, int(attempt))}


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
