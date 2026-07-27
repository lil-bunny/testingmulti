"""Shipper-domain helpers for load-tendering ack / routing-guide decisions."""

from __future__ import annotations

from typing import Any

from app.domain.load_tendering_settings import tenant_settings_root


def email_domain(address: str | None) -> str | None:
    """Return the lowercase domain of an email address, or ``None``."""
    email = str(address or "").strip().lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip()
    return domain or None


def shipper_domain_from_tenant_settings(state_or_data: Any) -> str | None:
    """
    Shipper domain from ``tenant_settings.inbound_routing_emails[0]``.

    Used to treat rejects from the same domain as terminal (no next-carrier advance).
    """
    root = tenant_settings_root(state_or_data)
    emails = root.get("inbound_routing_emails")
    if not isinstance(emails, list) or not emails:
        return None
    return email_domain(emails[0] if emails[0] is not None else None)


def is_shipper_domain_email(
    address: str | None,
    *,
    shipper_domain: str | None,
) -> bool:
    """True when ``address`` is on ``shipper_domain`` (or a subdomain)."""
    domain = str(shipper_domain or "").strip().lower()
    if not domain:
        return False
    addr_domain = email_domain(address)
    if not addr_domain:
        return False
    return addr_domain == domain or addr_domain.endswith(f".{domain}")


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
