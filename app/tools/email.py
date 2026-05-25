from typing import Any, Dict, List, Optional, Set

from app.core.config import settings
from app.core.logger import get_logger
from app.services.communications.service import CommunicationsService
from app.domain.tenant_settings.email_recipients import (
    coerce_email_list,
    unipile_recipients_from_addresses,
)
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)


def _record_outbound_communication(
    *,
    tenant_id: str | None,
    communication_metadata: dict[str, Any] | None,
    body: str,
    subject: str | None,
    result: dict[str, Any] | None,
    thread_id: str | None = None,
    to: Any = None,
    cc: Any = None,
    bcc: Any = None,
    account_id: str | None = None,
) -> None:
    if not tenant_id or not isinstance(result, dict) or not result.get("success"):
        return
    CommunicationsService().record_outbound_from_send(
        tenant_id,
        send_result=result,
        body=body,
        subject=subject,
        thread_id=thread_id or result.get("thread_id"),
        to=to,
        cc=cc,
        bcc=bcc,
        account_id=account_id,
        extra_metadata=communication_metadata,
    )

# Private helpers

def _normalize_email(e: Any) -> str:
    return (str(e) if e else "").strip().lower()


def _unipile_recipient_list(field: Any, *, required: bool) -> List[Dict[str, str]]:
    addrs = coerce_email_list(field, required=required)
    return unipile_recipients_from_addresses(addrs)


def _attendee_to_recipient(att: Any) -> Optional[Dict[str, str]]:
    """Convert a Unipile attendee dict to a {identifier, display_name} recipient."""
    if not isinstance(att, dict):
        return None
    ident = att.get("identifier")
    if not ident or "@" not in str(ident):
        return None
    return {
        "identifier": str(ident),
        "display_name": att.get("display_name") or str(ident).split("@")[0],
    }


def _resolve_parent_id(
    unipile: Unipile,
    latest_email: Dict,
    reply_to_message_id: Optional[str],
    account_id: Optional[str],
) -> str:
    """
    Resolve the internal Unipile email `id` to use as `reply_to`.
    Prefers an explicit caller-supplied id; falls back to latest email's id.
    """
    if reply_to_message_id:
        reply_to_message_id = str(reply_to_message_id).strip()
        if not reply_to_message_id:
            raise UnipileException("reply_to_message_id was provided but empty")

        resolved = None
        try:
            resolved = unipile.get_email(reply_to_message_id, account_id=account_id)
        except Exception:
            logger.warning(f"[reply_to_thread] Could not resolve provider_id={reply_to_message_id}, using as-is")

        reply_to_id = (resolved.get("id") if isinstance(resolved, dict) else None) or reply_to_message_id
        return str(reply_to_id).strip()

    pid = latest_email.get("id") or latest_email.get("provider_id") or latest_email.get("message_id")
    if not pid:
        raise UnipileException(
            "Could not determine parent message id to reply to; pass reply_to_message_id explicitly"
        )
    return str(pid).strip()


def _build_reply_subject(original_subject: str, override: Optional[str] = None) -> str:
    """
    Pick subject from original thread first, fall back to override.
    Ensures a 'Re: ' prefix exists (case-insensitive check).
    """
    subj = original_subject.strip() if original_subject and original_subject.strip() else None
    if not subj and override:
        subj = str(override).strip() or None
    if not subj:
        raise UnipileException("No subject found in thread and no override provided")

    low = subj.lstrip().lower()
    if low.startswith(("re:", "re :")):
        return subj
    return f"Re: {subj}"


def _build_recipients(
    latest_email: Dict,
    exclude_email: str,
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Build reply-all TO and CC lists from the latest email in a thread.

    Rules (mirrors standard reply-all behavior):
      - If we RECEIVED the latest email (role != 'sent'):
          TO  = from_attendee (the person who sent it to us)
                + all to_attendees (minus ourselves)
          CC  = all cc_attendees (minus ourselves)
      - If we SENT the latest email (role == 'sent'):
          TO  = all to_attendees (the people we sent to)
          CC  = all cc_attendees
      - Always excludes our own email from both lists.

    Returns (to_list, cc_list).
    """
    excluded: Set[str] = set()
    if exclude_email:
        excluded.add(_normalize_email(exclude_email))

    to_list: List[Dict[str, str]] = []
    cc_list: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def _add(recipient: Optional[Dict], target: List[Dict]) -> None:
        if not recipient or not recipient.get("identifier"):
            return
        norm = _normalize_email(recipient["identifier"])
        if norm in excluded or norm in seen:
            return
        seen.add(norm)
        target.append(recipient)

    role = latest_email.get("role")
    from_attendee = latest_email.get("from_attendee")
    to_attendees = latest_email.get("to_attendees") or []
    cc_attendees = latest_email.get("cc_attendees") or []

    if role != "sent":
        _add(_attendee_to_recipient(from_attendee), to_list)

    for att in to_attendees:
        _add(_attendee_to_recipient(att), to_list)

    for att in cc_attendees:
        _add(_attendee_to_recipient(att), cc_list)

    return to_list, cc_list


def _thread_email_summary(email: Dict) -> Dict[str, Any]:
    """Compact dict for logs (no body)."""
    subj = (email.get("subject") or "").strip()
    return {
        "role": email.get("role"),
        "date": email.get("date"),
        "id": email.get("id"),
        "provider_id": email.get("provider_id"),
        "message_id": email.get("message_id"),
        "subject": subj[:200] + ("…" if len(subj) > 200 else ""),
    }


def _merge_cc(
    thread_cc: List[Dict[str, str]],
    upstream_cc: Optional[List[Dict[str, Any]]],
    exclude_email: str,
    to_recipients: List[Dict[str, str]],
) -> Optional[List[Dict[str, str]]]:
    """Merge upstream caller CC with thread CC, deduplicating against TO and self."""
    excluded = {_normalize_email(exclude_email)} if exclude_email else set()
    to_norm = {_normalize_email(r.get("identifier")) for r in to_recipients}
    seen = {_normalize_email(c.get("identifier")) for c in thread_cc}

    merged = list(thread_cc)

    for c in (upstream_cc or []):
        if not isinstance(c, dict):
            continue
        ident = c.get("identifier") or c.get("email") or c.get("email_address")
        if not ident or not isinstance(ident, str) or "@" not in ident:
            continue
        norm = _normalize_email(ident)
        if norm in excluded or norm in to_norm or norm in seen:
            continue
        seen.add(norm)
        merged.append({"identifier": ident, "display_name": c.get("display_name") or ident.split("@")[0]})

    return merged or None


# Public tools


def send_unipile_thread_reply(
    thread_id: str,
    account_id: str,
    subject: str,
    body: str,
) -> bool:
    """In-thread reply via Unipile (wraps ``reply_to_thread``; returns False on failure)."""
    try:
        reply_to_thread(
            thread_id=thread_id,
            body=body,
            account_id=account_id,
            subject=subject or None,
        )
        return True
    except UnipileException as e:
        logger.warning("Unipile thread reply failed: %s", e)
        return False
    except Exception:
        logger.exception("Unexpected error in send_unipile_thread_reply")
        return False


def send_email(
    to,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    thread_id: Optional[str] = None,
    account_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    communication_metadata: Optional[dict[str, Any]] = None,
    cc: Any = None,
    bcc: Any = None,
):
    """
    POD request / reminder delivery. If ``thread_id`` is set, reply in thread; else if ``to``
    has at least one valid address, send a new message. Requires ``UNIPILE_API_KEY`` and
    sending ``account_id`` (argument or ``settings.UNIPILE_ACCOUNT_ID``).

    ``to``, ``cc``, and ``bcc`` accept a single email string or a list of strings.

    ``subject`` is optional; empty/missing values default to ``"POD Request"``.
    """
    subject = subject or "POD Request"
    body = (body or "").strip() or settings.POD_REMINDER_EMAIL_BODY
    tid = (thread_id or "").strip()
    acc = (account_id or settings.UNIPILE_ACCOUNT_ID or "").strip()
    api_key = (settings.UNIPILE_API_KEY or "").strip()

    if not api_key:
        logger.info(
            "send_email skipped: UNIPILE_API_KEY not set (to=%r subject=%r)",
            to,
            subject,
        )
        print(f"[EMAIL] to={to}, subject={subject} (no UNIPILE_API_KEY)")
        return

    if not acc:
        logger.info(
            "send_email skipped: no account_id and UNIPILE_ACCOUNT_ID unset (to=%r)",
            to,
        )
        print(f"[EMAIL] to={to}, subject={subject} (no account_id)")
        return

    if tid:
        return reply_to_thread(
            thread_id=tid,
            body=body,
            account_id=acc,
            subject=subject,
            tenant_id=tenant_id,
            communication_metadata=communication_metadata,
        )

    try:
        to_recipients = _unipile_recipient_list(to, required=True)
    except ValueError as exc:
        raise UnipileException(
            "send_email: no thread_id and no valid `to` address; nothing sent "
            f"(subject={subject!r}): {exc}"
        ) from exc

    cc_recipients = _unipile_recipient_list(cc, required=False) or None
    bcc_recipients = _unipile_recipient_list(bcc, required=False) or None

    unipile = Unipile()
    out = unipile.send_email(
        to=to_recipients,
        subject=subject,
        body=body,
        account_id=acc,
        cc=cc_recipients,
        bcc=bcc_recipients,
    )
    if not out.get("success"):
        err = out.get("error") or "Unipile send_email failed"
        logger.warning("send_email: Unipile send failed: %s", err)
        raise UnipileException(str(err))
    to_logged = coerce_email_list(to, required=False)
    cc_logged = coerce_email_list(cc, required=False)
    bcc_logged = coerce_email_list(bcc, required=False)
    _record_outbound_communication(
        tenant_id=tenant_id,
        communication_metadata=communication_metadata,
        body=body,
        subject=subject,
        result=out,
        to=to_logged or None,
        cc=cc_logged or None,
        bcc=bcc_logged or None,
        account_id=acc,
    )
    return out


def reply_to_thread(
    thread_id: str,
    body: str,
    account_id: str,
    subject: Optional[str] = None,
    reply_to_message_id: Optional[str] = None, # this could be either unipile_email_object[id] from retrieve email endpoint or provider_id (long alphanumeric used by outlook/gmail)
    cc: Optional[List[Dict[str, Any]]] = None,
    tenant_id: Optional[str] = None,
    communication_metadata: Optional[dict[str, Any]] = None,
):
    """
    Orchestrates a thread reply (reply-all):
    1. Resolve our email (to exclude from recipients)
    2. Fetch thread emails
    3. Resolve parent message id for Unipile reply_to
    4. Auto-resolve subject from latest message (unless overridden)
    5. Build reply-all TO + CC lists
    6. Merge any upstream CC, deduplicate
    7. Send via Unipile
    """
    if not thread_id:
        raise UnipileException("thread_id is required to reply to a thread")

    unipile = Unipile()

    # 1) Resolve our email to exclude from recipients
    exclude_email = unipile.get_account_email(account_id)

    # 2) Fetch all emails in thread
    emails_result = unipile.list_emails(account_id=account_id, thread_id=thread_id, limit=50)
    emails = emails_result.get("items", []) if isinstance(emails_result, dict) else []
    if not emails:
        raise UnipileException(f"No emails found for thread_id={thread_id}")

    sorted_emails = sorted(emails, key=lambda e: e.get("date") or "", reverse=True)
    latest_email = sorted_emails[0]

    role_counts: Dict[str, int] = {}
    for e in emails:
        r = str(e.get("role") or "?")
        role_counts[r] = role_counts.get(r, 0) + 1

    # 3) Resolve parent message id
    reply_to_id = _resolve_parent_id(unipile, latest_email, reply_to_message_id, account_id)
    logger.info("reply_to_thread: resolved reply_to_id=%s", reply_to_id)

    # 4) Subject: use latest email's subject unless upstream overrides
    original_subject = (latest_email.get("subject") or "").strip()
    effective_subject = _build_reply_subject(original_subject, subject)

    # 5) Reply-all: build TO and CC from latest email
    to_list, thread_cc = _build_recipients(latest_email, exclude_email)
    if not to_list:
        raise UnipileException("Could not determine reply recipients from the thread")

    # 6) Merge upstream CC with thread CC and dedup
    cc_final = _merge_cc(thread_cc, cc, exclude_email, to_list)

    # 7) Send
    result = unipile.send_email(
        to=to_list,
        subject=effective_subject,
        body=body,
        account_id=account_id,
        reply_to=reply_to_id,
        cc=cc_final,
    )

    result.setdefault("thread_id", thread_id)
    result.setdefault("reply_to_message_id", reply_to_id)
    if not result.get("success", True):
        logger.warning(
            "reply_to_thread: Unipile send failed thread_id=%s reply_to_id=%s err=%s details=%s",
            thread_id,
            reply_to_id,
            result.get("error"),
            result.get("error_details"),
        )
    else:
        _record_outbound_communication(
            tenant_id=tenant_id,
            communication_metadata=communication_metadata,
            body=body,
            subject=effective_subject,
            result=result,
            thread_id=thread_id,
            to=to_list,
            cc=cc_final,
            account_id=account_id,
        )
    return result

def detect_attachment_bytes_type(file_content: bytes) -> tuple[str, str]:
    """Infer file extension and MIME type from magic bytes (email / ratecon uploads)."""
    if file_content.startswith(b"%PDF"):
        return "pdf", "application/pdf"
    if file_content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if file_content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if file_content.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if file_content.startswith(b"RIFF") and len(file_content) >= 12 and file_content[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "bin", "application/octet-stream"


def get_email_attachments(email_id, attachment_id, account_id):
    unipile = Unipile()
    file_content = unipile.get_email_attachment(email_id, attachment_id, account_id)
    return file_content
