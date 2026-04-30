from typing import Any, Dict, List, Optional, Set
from app.services.unipile_service import Unipile, UnipileException


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

def send_email(to, subject, body):
    print(f"[EMAIL] to={to}, subject={subject}")  # TO-DO


def reply_to_thread(
    thread_id: str,
    body: str,
    account_id: str,
    subject: Optional[str] = None,
    reply_to_message_id: Optional[str] = None,
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

    # 3) Resolve parent message id
    reply_to_id = _resolve_parent_id(unipile, latest_email, reply_to_message_id, account_id)

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
    print(f"[reply_to_thread] thread_id={thread_id}, to={[r['identifier'] for r in to_list]}, cc={[c['identifier'] for c in (cc_final or [])]}, subject={effective_subject}")
    return result

def ingest_email(payload):
    # Prefer nested webhook payload to keep workflow state uncluttered.
    source = payload.get("unipile_webhook_payload", payload)

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


def get_email_attachments(email_id, attachment_id, account_id):
    unipile = Unipile()
    file_content = unipile.get_email_attachment(email_id, attachment_id, account_id)
    return file_content