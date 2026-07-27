"""Read POD lifecycle config from workflow state / Celery payload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.load_tendering_settings import tenant_settings_root
from app.domain.state import workflow_state_data
from app.domain.tenant_settings.email_recipients import unipile_recipients_from_addresses

MIKEY_ACCOUNT_ID_KEY = "mikey_account_id"


@dataclass(frozen=True)
class MikeyMailbox:
    account_id: str
    email_alias: str | None = None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def parse_mikey_mailbox(raw: Any) -> MikeyMailbox | None:
    """Parse ``mikey_account_id`` string or ``{account_id, email_alias?}`` object."""
    if raw is None:
        return None
    if isinstance(raw, str):
        account_id = _clean(raw)
        return MikeyMailbox(account_id=account_id) if account_id else None
    if isinstance(raw, dict):
        account_id = _clean(raw.get("account_id"))
        if not account_id:
            return None
        alias = _clean(raw.get("email_alias"))
        return MikeyMailbox(account_id=account_id, email_alias=alias)
    return None


def mikey_mailbox_from_tenant_settings(state_or_data: Any) -> MikeyMailbox | None:
    """Unipile sender mailbox for T3RA mail (``tenants.settings`` root)."""
    root = tenant_settings_root(state_or_data)
    return parse_mikey_mailbox(root.get(MIKEY_ACCOUNT_ID_KEY))


def mikey_unipile_from(mailbox: MikeyMailbox) -> dict[str, str] | None:
    """Build Unipile ``from`` recipient when ``email_alias`` is configured."""
    if not mailbox.email_alias:
        return None
    recipients = unipile_recipients_from_addresses([mailbox.email_alias])
    return recipients[0] if recipients else None


def resolve_mikey_mailbox(state_or_data: Any) -> MikeyMailbox | None:
    """
    Resolve Unipile mailbox for T3RA POD / driver-assignment send.

    Precedence: explicit payload ``account_id`` (alias from tenant) → tenant
    ``mikey_account_id``.
    """
    data = workflow_state_data(state_or_data)
    explicit = _clean(data.get("account_id"))
    tenant_mailbox = mikey_mailbox_from_tenant_settings(state_or_data)

    if explicit:
        alias = tenant_mailbox.email_alias if tenant_mailbox else None
        return MikeyMailbox(account_id=explicit, email_alias=alias)

    if tenant_mailbox:
        return tenant_mailbox

    return None


def mikey_account_id_from_tenant_settings(state_or_data: Any) -> str | None:
    """Unipile sender account id for T3RA POD mail (``tenants.settings`` root)."""
    mailbox = mikey_mailbox_from_tenant_settings(state_or_data)
    return mailbox.account_id if mailbox else None


def resolve_pod_sender_account_id(state_or_data: Any) -> str | None:
    """
    Resolve Unipile ``account_id`` for POD send/fetch.

    Precedence: explicit payload ``account_id`` → ``mikey_account_id``.
    """
    mailbox = resolve_mikey_mailbox(state_or_data)
    return mailbox.account_id if mailbox else None


def hydrate_pod_account_id(data: dict[str, Any]) -> None:
    """Set ``account_id`` on reminder/workflow payload when absent."""
    if _clean(data.get("account_id")):
        return
    resolved = resolve_pod_sender_account_id(data)
    if resolved:
        data["account_id"] = resolved
