"""Gelita shipper-domain helpers for load-tendering ack / routing-guide decisions."""

from __future__ import annotations

from typing import Any

GELITA_SHIPPER_EMAIL_DOMAIN = "gelita.com"


def is_gelita_shipper_email(address: str | None) -> bool:
    """True when ``address`` is on ``@gelita.com`` (or a subdomain)."""
    email = str(address or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip()
    if not domain:
        return False
    return domain == GELITA_SHIPPER_EMAIL_DOMAIN or domain.endswith(
        f".{GELITA_SHIPPER_EMAIL_DOMAIN}"
    )


def reply_from_email_from_state_data(data: dict[str, Any] | None) -> str | None:
    """Extract inbound From from Unipile webhook fields on workflow state."""
    if not isinstance(data, dict):
        return None
    from_att = data.get("from_attendee")
    if isinstance(from_att, dict):
        ident = from_att.get("identifier")
        if ident is not None and "@" in str(ident):
            text = str(ident).strip()
            return text or None
    raw = data.get("from")
    if isinstance(raw, str):
        text = raw.strip()
        if text and "@" in text:
            return text
    return None
