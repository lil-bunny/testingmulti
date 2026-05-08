from typing import Any, Dict, List, Optional, Set

from app.core.config import settings
from app.core.logger import get_logger
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)

# Private helpers

def _normalize_email(e: Any) -> str:
    return (str(e) if e else "").strip().lower()


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
            print(f"[reply_to_thread] Could not resolve provider_id={reply_to_message_id}, using as-is")

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
):
    """
    POD request / reminder delivery. If ``thread_id`` is set, reply in thread; else if ``to``
    is an email, send a new message. Requires ``UNIPILE_API_KEY`` and sending ``account_id``
    (argument or ``settings.UNIPILE_ACCOUNT_ID``).

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
        reply_to_thread(
            thread_id=tid,
            body=body,
            account_id=acc,
            # subject=subject,
        )
        return

    to_addr = (str(to).strip() if to else "") or ""
    if "@" in to_addr:
        unipile = Unipile()
        recipients: List[Dict[str, str]] = [
            {
                "identifier": to_addr,
                "display_name": to_addr.split("@", 1)[0],
            }
        ]
        out = unipile.send_email(
            to=recipients,
            subject=subject,
            body=body,
            account_id=acc,
        )
        if not out.get("success"):
            err = out.get("error") or "Unipile send_email failed"
            logger.warning("send_email: Unipile send failed: %s", err)
            raise UnipileException(str(err))
        return

    raise UnipileException(
        "send_email: no thread_id and no valid `to` address; nothing sent "
        f"(subject={subject!r})"
    )


def reply_to_thread(
    thread_id: str,
    body: str,
    account_id: str,
    subject: Optional[str] = None,
    reply_to_message_id: Optional[str] = None, # this could be either unipile_email_object[id] from retrieve email endpoint or provider_id (long alphanumeric used by outlook/gmail)
    cc: Optional[List[Dict[str, Any]]] = None,
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
    logger.info(
        "reply_to_thread: thread_id=%s account_id=%s message_count=%s role_counts=%s "
        "latest_by_date=%s explicit_reply_to_message_id=%s",
        thread_id,
        account_id,
        len(emails),
        role_counts,
        _thread_email_summary(latest_email),
        reply_to_message_id,
    )

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
        logger.info(
            "reply_to_thread: sent ok thread_id=%s to=%s cc=%s subject=%s tracking_id=%s",
            thread_id,
            [r["identifier"] for r in to_list],
            [c["identifier"] for c in (cc_final or [])],
            effective_subject,
            result.get("tracking_id") or result.get("message_id"),
        )
    return result

def ingest_email(payload):
    # Prefer nested webhook payload to keep workflow state uncluttered.
    source = payload

    return {
        "attachments": source.get("attachments"),
        "thread_id": source.get("thread_id"),
        "body": source.get("body"),
        "subject": source.get("subject"),
        "has_attachments": source.get("has_attachments"),
        "role": source.get("role"),
        "email_id": source.get("email_id"),
        "account_id": source.get("account_id"),
        "provider_id": source.get("provider_id"),
        "message_id": source.get("message_id"),
        "from_attendee": source.get("from_attendee"),
        "to_attendees": source.get("to_attendees"),
        "cc_attendees": source.get("cc_attendees"),
        "in_reply_to": source.get("in_reply_to"),
        "date": source.get("date"),
    }


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