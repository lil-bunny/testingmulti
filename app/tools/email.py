import json
import re
from typing import Any, Optional
from urllib.parse import quote, urljoin

import httpx

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


def send_email(to, subject, body):
    print(f"[EMAIL] to={to}, subject={subject}")  # TO-DO


def ingest_email(payload):
    return {
        "attachments": payload.get("attachments", []),
        "thread_id": payload.get("thread_id", "thread-123"),
        "body": payload.get("body", ""),
    }


def _unipile_headers() -> dict[str, str]:
    key = settings.UNIPILE_API_KEY or ""
    return {
        "X-API-KEY": key,
        "accept": "application/json",
    }


def unipile_list_thread_emails(thread_id: str, account_id: str) -> list[dict[str, Any]]:
    """GET /api/v1/emails for one thread; returns raw `items` list (may be empty)."""
    if not settings.UNIPILE_API_KEY or not thread_id.strip() or not account_id.strip():
        return []
    base = settings.UNIPILE_BASE_URL.rstrip("/")
    q_tid = quote(thread_id, safe="")
    q_acc = quote(account_id, safe="")
    url = f"{base}/api/v1/emails?thread_id={q_tid}&account_id={q_acc}"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=_unipile_headers())
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Unipile list emails failed: %s", e)
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


def _attendees_json(attendees: Any) -> str:
    if not isinstance(attendees, list) or not attendees:
        return "[]"
    out = []
    for a in attendees:
        if not isinstance(a, dict):
            continue
        ident = a.get("identifier")
        if not ident:
            continue
        out.append(
            {
                "identifier": ident,
                "display_name": a.get("display_name") or "",
            }
        )
    return json.dumps(out)


def _reply_fields_from_last_email(last: dict[str, Any]) -> Optional[dict[str, str]]:
    """Minimal fields for Unipile reply POST (multipart), derived from list API item."""
    account_id = last.get("account_id")
    provider_id = last.get("provider_id")
    from_a = last.get("from_attendee")
    if not account_id or not provider_id or not isinstance(from_a, dict):
        return None
    identifier = from_a.get("identifier")
    if not identifier:
        return None
    to_src = last.get("to_attendees")
    to_json = _attendees_json(to_src)
    if to_json == "[]":
        return None
    return {
        "account_id": str(account_id),
        "identifier": str(identifier),
        "to": to_json,
        "reply_to": str(provider_id),
    }


_RE_PREFIX = re.compile(r"(?i)^re\s*:\s*(.*)$")


def _strip_reply_prefixes(subject: str) -> str:
    """Remove repeated Re:/RE: (any casing) so we never send Re: Re: …"""
    s = (subject or "").strip()
    while s:
        m = _RE_PREFIX.match(s)
        if not m:
            break
        s = m.group(1).strip()
    return s


def _reply_subject_line(thread_subject: str | None, fallback_subject: str) -> str:
    """
    One well-formed reply subject: "Re: <root>".
    Prefer the last message's subject; use fallback (e.g. reminder title) if empty.
    """
    raw = (thread_subject or "").strip() or (fallback_subject or "").strip()
    core = _strip_reply_prefixes(raw)
    return f"Re: {core}" if core else "Re:"


def send_unipile_thread_reply(
    thread_id: str,
    account_id: str,
    subject: str,
    body: str,
) -> bool:
    """
    List thread emails, take the last message, POST in-thread reply via Unipile.
    """
    if not settings.UNIPILE_API_KEY:
        return False
    items = unipile_list_thread_emails(thread_id, account_id)
    if not items:
        logger.warning("Unipile reply skipped: no messages for thread %s", thread_id[:24])
        return False
    last = items[-1]
    fields = _reply_fields_from_last_email(last)
    if not fields:
        logger.warning("Unipile reply skipped: cannot build reply from last message")
        return False

    out_subject = _reply_subject_line(last.get("subject"), subject)

    base = settings.UNIPILE_BASE_URL.rstrip("/")
    url = urljoin(base + "/", "api/v1/emails")
    form = {
        "account_id": (None, fields["account_id"]),
        "identifier": (None, fields["identifier"]),
        "to": (None, fields["to"]),
        "subject": (None, out_subject),
        "body": (None, body),
        "reply_to": (None, fields["reply_to"]),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=_unipile_headers(), files=form)
            r.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Unipile send reply failed: %s", e)
        return False
    return True
