"""Helpers for linking graph state to ``communications`` / ``activity_logs``."""

from __future__ import annotations

from typing import Any


def stash_communication_id(state: Any, send_result: dict[str, Any] | None) -> str | None:
    """Copy ``communication_id`` from a send result onto ``state.data``."""
    if not isinstance(send_result, dict):
        return None
    comm_id = send_result.get("communication_id")
    if not comm_id:
        return None
    cid = str(comm_id).strip()
    if not cid:
        return None
    data = getattr(state, "data", None)
    if isinstance(data, dict):
        data["communication_id"] = cid
    return cid


def outbound_email_metadata(
    *,
    to: Any = None,
    cc: Any = None,
    bcc: Any = None,
    from_addresses: Any = None,
) -> dict[str, list[str]]:
    """Normalize recipient lists for ``activity_logs.metadata``."""
    from app.domain.tenant_settings.email_recipients import coerce_email_list

    return {
        "escalation_to": coerce_email_list(to, required=False),
        "escalation_cc": coerce_email_list(cc, required=False),
        "escalation_bcc": coerce_email_list(bcc, required=False),
        "escalation_from": coerce_email_list(from_addresses, required=False),
    }
