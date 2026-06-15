"""Normalize tenant-configured email lists and map to Unipile recipient dicts."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, field_validator


def coerce_email_list(value: Any, *, required: bool) -> list[str]:
    """
    Accept a single address, a list of addresses, or empty/None.

    Strips, dedupes case-insensitively, drops blanks and strings without ``@``.
    Returns addresses in original casing (except dedupe key is lowercase).
    """
    if value is None:
        items: list[str] = []
    elif isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [str(x) for x in value]
    else:
        items = [str(value)]

    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        addr = str(raw or "").strip()
        if not addr or "@" not in addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)

    if required and not out:
        raise ValueError("at least one valid email address is required")
    return out


def normalize_emails_for_matching(value: Any, *, required: bool) -> list[str]:
    """
    Canonical form for routing lookup and ``inbound_routing_emails`` storage:
    strip, lowercase, dedupe, drop invalid; raise if ``required`` and empty.
    """
    return [addr.lower() for addr in coerce_email_list(value, required=required)]


def normalize_inbound_routing_emails(value: Any) -> list[str]:
    """Validate and normalize ``inbound_routing_emails`` (lowercase, strip, dedupe, min 1)."""
    return normalize_emails_for_matching(value, required=True)


InboundRoutingEmails = Annotated[
    list[str],
    BeforeValidator(normalize_inbound_routing_emails),
    Field(min_length=1),
]


def unipile_recipients_from_addresses(addresses: list[str]) -> list[dict[str, str]]:
    """Build Unipile ``to`` / ``cc`` / ``bcc`` payload entries."""
    return [
        {
            "identifier": addr,
            "display_name": addr.split("@", 1)[0],
        }
        for addr in addresses
    ]


class EmailRecipients(BaseModel):
    """Parsed TO / CC / BCC for one outbound email action."""

    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)

    @field_validator("to", mode="before")
    @classmethod
    def _validate_to(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=True)

    @field_validator("cc", "bcc", mode="before")
    @classmethod
    def _validate_cc_bcc(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=False)

    def to_unipile_to(self) -> list[dict[str, str]]:
        return unipile_recipients_from_addresses(self.to)

    def to_unipile_cc(self) -> list[dict[str, str]] | None:
        if not self.cc:
            return None
        return unipile_recipients_from_addresses(self.cc)

    def to_unipile_bcc(self) -> list[dict[str, str]] | None:
        if not self.bcc:
            return None
        return unipile_recipients_from_addresses(self.bcc)


def email_recipients_from_action_cfg(
    cfg: dict[str, Any],
    *,
    to_key: str,
    cc_key: str,
    bcc_key: str,
) -> EmailRecipients:
    """Parse TO/CC/BCC keys from a load-tendering action settings dict."""
    return EmailRecipients(
        to=cfg.get(to_key),
        cc=cfg.get(cc_key),
        bcc=cfg.get(bcc_key),
    )
