"""Map channel payloads and send results to ``communications`` row fields."""

from __future__ import annotations

from html import unescape
import re
from typing import Any

# from app.domain.email_body_for_llm import normalize_email_body_for_llm
from app.domain.unipile_email import attachments_metadata_from_payload

_QUOTE_HTML_RE = re.compile(r'<div[^>]*class="[^"]*gmail_quote', re.IGNORECASE)
_BLOCKQUOTE_RE = re.compile(r"<blockquote\b", re.IGNORECASE)
_OUTLOOK_FWD_BLOCK_RE = re.compile(
    r'<div[^>]*\bid=["\'][^"\']*divRplyFwdMsg["\'][^>]*>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
_OUTLOOK_APPEND_HTML_RE = re.compile(
    r'<div[^>]*\bid=["\'][^"\']*appendonsend["\'][^>]*>\s*</div>',
    re.IGNORECASE,
)
_OUTLOOK_FWD_HEADER_DIV_RE = re.compile(
    r"""
    <div[^>]*>
        .*?<b>\s*From:\s*</b>.*?
        <b>\s*Sent:\s*</b>.*?
        (?:<b>\s*To:\s*</b>.*?)?
        (?:<b>\s*(?:Cc|CC):\s*</b>.*?)?
        <b>\s*Subject:\s*</b>.*?
    </div>
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
_HR_TAG_RE = re.compile(r"<hr\b[^>]*>", re.IGNORECASE)
_ON_WROTE_RE = re.compile(r"\bOn .+ wrote:\s*", re.IGNORECASE | re.DOTALL)
_ORIGINAL_MESSAGE_RE = re.compile(
    r"-{3,}\s*Original Message\s*-{3,}",
    re.IGNORECASE,
)
_FORWARD_HEADER_BLOCK_RE = re.compile(
    r"""
    \bFrom:\s*.+?(?:\n|$)
    \s*Sent:\s*.+?(?:\n|$)
    (?:\s*To:\s*.+?(?:\n|$))?
    (?:\s*(?:Cc|CC):\s*.+?(?:\n|$))?
    \s*Subject:\s*.+?(?:\n|$)
    """,
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
)
_FORWARD_HEADER_PREFIX_RE = re.compile(
    r"^(?:From:\s*.+?(?:\n|$))"
    r"(?:\s*Sent:\s*.+?(?:\n|$))?"
    r"(?:\s*To:\s*.+?(?:\n|$))?"
    r"(?:\s*(?:Cc|CC):\s*.+?(?:\n|$))?"
    r"(?:\s*Subject:\s*.+?(?:\n|$))?\s*",
    re.IGNORECASE | re.MULTILINE,
)
_WS_RE = re.compile(r"\s+")
_OUTBOUND_LLM_SENDER = "ops_rep"


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return unescape(without_tags)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _strip_reply_quotes_only(html: str) -> str:
    """Drop nested reply quotes; used on the latest-reply segment only."""
    for pattern in (_QUOTE_HTML_RE, _BLOCKQUOTE_RE):
        match = pattern.search(html)
        if match:
            html = html[: match.start()].strip()
            break
    return html


def _process_forward_html_segment(html: str) -> str:
    """Strip forward header noise from a post-``<hr>`` segment; keep load details."""
    html = _OUTLOOK_APPEND_HTML_RE.sub("", html)
    html = _OUTLOOK_FWD_BLOCK_RE.sub("", html)
    html = _OUTLOOK_FWD_HEADER_DIV_RE.sub("", html)
    return _strip_reply_quotes_only(html)


def _strip_quoted_html(html: str) -> str:
    """
    Remove forward/reply noise from HTML while keeping substantive body text.

    When Outlook/Gmail insert ``<hr>`` between a short new reply and a forward
    block, keep both the leading reply and the forwarded load details (minus
    From/Sent/To/Subject headers). When the segment after ``<hr>`` is only a
    quoted prior reply, drop it.
    """
    hr_match = _HR_TAG_RE.search(html)
    if hr_match:
        head_html = _strip_reply_quotes_only(html[: hr_match.start()])
        tail_raw = html[hr_match.end() :]
        tail_html = _process_forward_html_segment(tail_raw)
        head = _collapse_ws(_strip_html(head_html))
        tail = _collapse_ws(_strip_html(tail_html))
        # ``divRplyFwdMsg`` after ``<hr>`` marks a quoted reply chain when there is
        # also new reply text before the rule; pure forwards keep the tail body.
        reply_forward = _OUTLOOK_FWD_BLOCK_RE.search(tail_raw) is not None and bool(head)
        if reply_forward:
            return head
        if head and tail:
            return f"{head} {tail}"
        if head:
            return head
        if tail:
            return tail
        return ""

    html = _process_forward_html_segment(html)
    return _strip_reply_quotes_only(html)


def _strip_forward_header_prefix(text: str) -> str:
    """Drop a leading From/Sent/To/Subject block; keep operational text after it."""
    stripped = text
    while True:
        match = _FORWARD_HEADER_PREFIX_RE.match(stripped)
        if not match:
            break
        stripped = stripped[match.end() :].strip()
    return stripped

def _strip_forward_header_blocks(text: str) -> str:
    """
    Remove Outlook-style forwarding metadata while preserving the
    forwarded message body.

    Example:

        Howdy

        From: Bob
        Sent: Monday...
        To: Alice
        Subject: Shipment

        Pickup address...

    becomes:

        Howdy

        Pickup address...
    """
    return _FORWARD_HEADER_BLOCK_RE.sub("\n", text)

def _strip_quoted_plain(text: str) -> str:
    """
    Remove reply-chain noise while preserving forwarded shipment/order
    content. Forward headers (From/Sent/To/Subject) are stripped but
    the forwarded body remains.
    """

    text = _strip_forward_header_blocks(text)

    for pattern in (_ON_WROTE_RE, _ORIGINAL_MESSAGE_RE):
        match = pattern.search(text)
        if match:
            text = text[: match.start()].strip()

    return _strip_forward_header_prefix(text)
    
def normalize_email_body_for_llm(*, body: str | None = None) -> str:
    """Plain email text for LLM input: strip quote/header noise, keep load details."""
    raw = (body or "").strip()
    if not raw:
        return ""

    if "<" in raw:
        raw = _strip_quoted_html(raw)
        text = _strip_html(raw)
    else:
        text = raw

    text = _strip_quoted_plain(text)
    return _collapse_ws(text)


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


def _sender_for_llm_turn(row: dict[str, Any], meta: dict[str, Any]) -> str:
    """Sender label for LLM thread headers; outbound system sends use ``ops_rep``."""
    sender = str(meta.get("from") or "").strip()
    if sender:
        return sender
    if str(row.get("direction") or "").strip().lower() == "outbound":
        return _OUTBOUND_LLM_SENDER
    return "unknown"


def _turn_header(index: int, row: dict[str, Any]) -> str:
    """Factual per-email header: direction + sender/recipients."""
    meta = row.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    direction = str(row.get("direction") or "").strip() or "unknown"
    sender = _sender_for_llm_turn(row, meta)
    recipients = ", ".join(_recipient_identifiers(meta.get("to")))
    return f"email {index} [{direction} | from: {sender} | to: {recipients}]"


def format_labeled_email_thread_for_llm(turns: list[tuple[dict[str, Any], str]]) -> str:
    """Format ``(row, normalized_body)`` pairs as labeled ``email N [...]`` blocks."""
    parts: list[str] = []
    for index, (row, body) in enumerate(turns, start=1):
        parts.append(f"{_turn_header(index, row)}\n{body}")
    return "\n\n".join(parts)


def build_email_thread_llm_user_message(
    messages: list[dict[str, Any]],
    *,
    fallback_body: str | None = None,
    max_messages: int | None = None,
) -> str:
    """
    Build chronological thread text from ``communications`` rows (``content`` field).

    Each email is prefixed with a factual header (direction + from/to) so the LLM
    can attribute statements to senders. Falls back to a single normalized webhook
    body when no stored messages have text.
    """
    rows = list(messages)
    if max_messages is not None and max_messages > 0 and len(rows) > max_messages:
        rows = rows[-max_messages:]

    turns: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        body = normalize_email_body_for_llm(body=row.get("content"))
        if body:
            turns.append((row, body))
    if turns:
        return format_labeled_email_thread_for_llm(turns)

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
