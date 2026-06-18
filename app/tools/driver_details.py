"""Pure helpers for driver-details LLM output parsing (no I/O)."""

from __future__ import annotations

from typing import Any

from app.services.communications._mapper import normalize_email_body_for_llm

HAS_DETAILS = "has_details"
INSUFFICIENT = "insufficient"
DO_NOTHING = "do_nothing"

_DRIVER_DETAILS_DECISIONS = frozenset({HAS_DETAILS, INSUFFICIENT, DO_NOTHING})


def normalize_driver_reply_body(*, body: str | None = None) -> str:
    return normalize_email_body_for_llm(body=body)


def _clean_field(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def normalize_driver_block(raw: Any) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        return {"name": None, "phone": None, "email": None}
    return {
        "name": _clean_field(raw.get("name")),
        "phone": _clean_field(raw.get("phone")),
        "email": _clean_field(raw.get("email")),
    }


def normalize_driver_details_decision(raw: dict[str, Any]) -> str:
    decision = str(raw.get("decision") or "").strip().lower()
    if decision in _DRIVER_DETAILS_DECISIONS:
        return decision
    return DO_NOTHING


def has_partial_driver_fields(driver: dict[str, str | None]) -> bool:
    """True when at least one driver field is present but not a full ``has_details`` set."""
    if validate_minimum_driver_fields(driver) == HAS_DETAILS:
        return False
    return bool(driver.get("name") or driver.get("phone") or driver.get("email"))


def validate_minimum_driver_fields(driver: dict[str, str | None]) -> str:
    """Downgrade to ``insufficient`` when name or contact is missing."""
    name = driver.get("name")
    phone = driver.get("phone")
    email = driver.get("email")
    if name and (phone or email):
        return HAS_DETAILS
    return INSUFFICIENT


def build_driver_details_result(
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Map LLM JSON to normalized decision, driver fields, confidence, reason."""
    driver = normalize_driver_block(raw.get("driver"))
    decision = normalize_driver_details_decision(raw)
    if decision == HAS_DETAILS:
        decision = validate_minimum_driver_fields(driver)
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(raw.get("reason") or "").strip() or "no reason"
    return {
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
        "driver": driver,
    }
