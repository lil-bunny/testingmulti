"""Pure helpers for driver-details LLM output parsing (no I/O)."""

from __future__ import annotations

from typing import Any

from app.domain.email_body_for_llm import normalize_email_body_for_llm

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


def normalize_phone_digits(phone: str | None) -> str:
    """Digits only; US numbers compare on national number (strip leading 1)."""
    if not phone:
        return ""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) > 10:
        return digits[-10:]
    return digits


def phones_match(a: str | None, b: str | None) -> bool:
    left = normalize_phone_digits(a)
    right = normalize_phone_digits(b)
    return bool(left) and left == right


def _normalize_name(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def names_match(a: str | None, b: str | None) -> bool:
    left = _normalize_name(a)
    right = _normalize_name(b)
    return bool(left) and left == right


def emails_match(a: str | None, b: str | None) -> bool:
    left = _normalize_email(a)
    right = _normalize_email(b)
    return bool(left) and left == right


def contact_row_name_phone(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Display name and primary phone from normalized Turvo contact row."""
    name = _clean_field(row.get("name"))
    phones = row.get("phones") or []
    phone = _clean_field(phones[0]) if phones else None
    return name, phone


def driver_block_name_phone(driver: dict[str, str | None]) -> tuple[str | None, str | None]:
    """Name and phone from a driver block (LLM extraction or create input)."""
    return _clean_field(driver.get("name")), _clean_field(driver.get("phone"))


def has_tms_searchable_fields(driver: dict[str, str | None]) -> bool:
    """Name or phone present — enough to attempt TMS contact search."""
    return bool((driver.get("name") or "").strip() or (driver.get("phone") or "").strip())


def can_create_tms_driver_contact(driver: dict[str, str | None]) -> bool:
    """Name plus phone or email — enough to create a new TMS driver contact."""
    name = (driver.get("name") or "").strip()
    return bool(name and ((driver.get("phone") or "").strip() or (driver.get("email") or "").strip()))


def is_tms_tracking_customer(
    customer_name: str | None,
    *,
    tracking_customer_names: frozenset[str] | None = None,
) -> bool:
    """True when shipment customer is in the tenant tracking-customer list."""
    names = tracking_customer_names or frozenset()
    if not names:
        return False
    return (customer_name or "").strip() in names


def render_driver_confirmation_html(
    template: str,
    *,
    driver_name: str | None = None,
    driver_phone: str | None = None,
) -> str:
    return (
        template.replace("{driver_name}", (driver_name or "").strip() or "—")
        .replace("{driver_phone}", (driver_phone or "").strip() or "—")
    )


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
