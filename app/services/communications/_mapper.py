"""Map channel payloads and send results to ``communications`` row fields."""

from __future__ import annotations

from typing import Any

from app.domain.email_body_for_llm import normalize_email_body_for_llm
from app.domain.unipile_email import attachments_metadata_from_payload


def format_email_thread_for_llm(bodies: list[str]) -> str:
    """Format normalized bodies as ``email 1`` … ``email N`` blocks for LLM user content."""
    parts: list[str] = []
    index = 0
    for raw in bodies:
        text = (raw or "").strip()
        if not text:
            continue
        index += 1
        parts.append(f"email {index}\n{text}")
    return "\n\n".join(parts)


def build_email_thread_llm_user_message(
    messages: list[dict[str, Any]],
    *,
    fallback_body: str | None = None,
    max_messages: int | None = None,
) -> str:
    """
    Build chronological thread text from ``communications`` rows (``content`` field).

    Falls back to a single normalized webhook body when no stored messages have text.
    """
    rows = list(messages)
    if max_messages is not None and max_messages > 0 and len(rows) > max_messages:
        rows = rows[-max_messages:]

    bodies = [
        normalize_email_body_for_llm(body=row.get("content"))
        for row in rows
    ]
    bodies = [b for b in bodies if b]
    if bodies:
        return format_email_thread_for_llm(bodies)

    return normalize_email_body_for_llm(body=fallback_body)


def resolve_email_content(
    *,
    body_html: str | None = None,
    body: str | None = None,
) -> str | None:
    """Prefer ``body_html``, then provider ``body``."""
    for raw in (body_html, body):
        if raw is not None and str(raw).strip():
            return str(raw)
    return None


def _attendee_emails(attendees: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(attendees, list):
        return out
    for att in attendees:
        if not isinstance(att, dict):
            continue
        ident = att.get("identifier")
        if ident and "@" in str(ident):
            out.append(str(ident))
    return out


def _from_attendee_email(payload: dict[str, Any]) -> str | None:
    from_att = payload.get("from_attendee")
    if isinstance(from_att, dict):
        ident = from_att.get("identifier")
        if ident and "@" in str(ident):
            return str(ident)
    return None


def inbound_metadata_from_payload(
    payload: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attachments = attachments_metadata_from_payload(payload)
    meta: dict[str, Any] = {
        "subject": str(payload.get("subject") or ""),
        "from": _from_attendee_email(payload),
        "to": _attendee_emails(payload.get("to_attendees")),
        "cc": _attendee_emails(payload.get("cc_attendees")),
        "bcc": _attendee_emails(payload.get("bcc_attendees")),
        "event": payload.get("event"),
        "account_id": payload.get("account_id"),
        "attachments": attachments,
    }
    if extra:
        meta.update(extra)
    return meta


def inbound_row_from_payload(
    payload: dict[str, Any],
    *,
    tenant_id: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    external_id = str(payload.get("email_id") or "").strip()
    if not external_id:
        return None
    thread_id = payload.get("thread_id")
    thread_s = str(thread_id).strip() if thread_id is not None else None
    if thread_s == "":
        thread_s = None
    content = resolve_email_content(
        body_html=payload.get("body_html"),
        body=payload.get("body"),
    )
    return {
        "tenant_id": tenant_id,
        "channel": "email",
        "direction": "inbound",
        "external_id": external_id,
        "thread_id": thread_s,
        "content": content,
        "metadata": inbound_metadata_from_payload(payload, extra=extra_metadata),
    }


def _recipient_identifiers(recipients: Any) -> list[str]:
    if not recipients:
        return []
    if isinstance(recipients, str):
        return [recipients] if "@" in recipients else []
    out: list[str] = []
    if isinstance(recipients, list):
        for item in recipients:
            if isinstance(item, str) and "@" in item:
                out.append(item)
            elif isinstance(item, dict):
                ident = item.get("identifier") or item.get("email")
                if ident and "@" in str(ident):
                    out.append(str(ident))
    return out


def outbound_metadata(
    *,
    subject: str | None,
    to: Any = None,
    cc: Any = None,
    bcc: Any = None,
    account_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "subject": str(subject or ""),
        "to": _recipient_identifiers(to),
        "cc": _recipient_identifiers(cc),
        "bcc": _recipient_identifiers(bcc),
    }
    if account_id:
        meta["account_id"] = account_id
    if extra:
        meta.update(extra)
    return meta


def outbound_row_from_send(
    *,
    tenant_id: str,
    send_result: dict[str, Any],
    body: str,
    subject: str | None = None,
    thread_id: str | None = None,
    to: Any = None,
    cc: Any = None,
    bcc: Any = None,
    account_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    workflow_run_id: str | None = None,
    channel: str = "email",
) -> dict[str, Any] | None:
    if not send_result.get("success"):
        return None
    external_id = str(
        send_result.get("message_id") or send_result.get("tracking_id") or ""
    ).strip()
    if not external_id and extra_metadata:
        external_id = str(extra_metadata.get("idempotency_key") or "").strip()
    if not external_id:
        return None
    tid = str(thread_id or send_result.get("thread_id") or "").strip() or None
    content = resolve_email_content(body_html=body)
    row: dict[str, Any] = {
        "tenant_id": tenant_id,
        "channel": channel,
        "direction": "outbound",
        "external_id": external_id,
        "thread_id": tid,
        "content": content,
        "metadata": outbound_metadata(
            subject=subject,
            to=to,
            cc=cc,
            bcc=bcc,
            account_id=account_id,
            extra=extra_metadata,
        ),
    }
    if workflow_run_id:
        row["workflow_run_id"] = workflow_run_id
    return row
