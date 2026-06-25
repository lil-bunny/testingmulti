"""Gelita routing-guide lane lookup and carrier waterfall policy."""

from __future__ import annotations

import re
from typing import Any

from thefuzz import fuzz

from app.domain.routing_guide.types import PlanCarriers, RoutingGuideRow

GELITA_PLAN_SLOTS: tuple[str, ...] = ("a", "b", "c")
GELITA_MAX_CARRIER_ATTEMPTS = 3

_ATTEMPT_TO_SLOT: dict[int, str] = {1: "a", 2: "b", 3: "c"}
_PARTNER_FUZZY_THRESHOLD = 80
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def gelita_normalize_lane_zip(value: Any) -> str:
    """Normalize US postal codes for Gelita zip-first lane lookup."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    compact = "".join(ch for ch in text if ch.isalnum())
    if not compact:
        return ""
    if compact.isdigit() and len(compact) >= 5:
        return compact[:5]
    return compact


def gelita_normalize_partner_label(value: Any) -> str:
    """Collapse partner text for fuzzy source-label comparison."""
    collapsed = " ".join(str(value or "").strip().casefold().split())
    return _NON_ALNUM_RE.sub("", collapsed)


def gelita_partner_matches_source_label(
    *,
    source_partner_label: str,
    customer_name: str,
    customer_aliases: list[str] | None = None,
    threshold: int = _PARTNER_FUZZY_THRESHOLD,
) -> bool:
    """True when ingest partner label matches guide ``customer_name`` or aliases."""
    needle = gelita_normalize_partner_label(source_partner_label)
    if not needle:
        return False
    candidates = [customer_name, *(customer_aliases or [])]
    for candidate in candidates:
        haystack = gelita_normalize_partner_label(candidate)
        if not haystack:
            continue
        if needle == haystack:
            return True
        if fuzz.token_set_ratio(needle, haystack) >= threshold:
            return True
    return False


def gelita_select_lane(
    candidates: list[RoutingGuideRow],
    *,
    source_partner_label: str,
) -> RoutingGuideRow | None:
    """Disambiguate zip collisions using Gelita LIEFMATCH-style partner labels."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    needle = str(source_partner_label or "").strip()
    if not needle:
        return None
    matched = [
        row
        for row in candidates
        if gelita_partner_matches_source_label(
            source_partner_label=needle,
            customer_name=row.customer_name,
            customer_aliases=row.customer_aliases,
        )
    ]
    if len(matched) == 1:
        return matched[0]
    return None


def gelita_plan_slot_for_attempt(attempt: int) -> str:
    """Map Gelita waterfall attempt 1/2/3 to carrier slots a/b/c."""
    return _ATTEMPT_TO_SLOT.get(max(int(attempt), 1), "c")


def gelita_plan_carrier_for_attempt(
    carriers: PlanCarriers,
    attempt: int,
) -> tuple[str, str]:
    """Return carrier name and email for a Gelita waterfall attempt."""
    slot_map = carriers.get(gelita_plan_slot_for_attempt(attempt), {})
    name, email = next(iter(slot_map.items()), ("", ""))
    return str(name).strip(), str(email).strip()
