from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.services.communications.service import CommunicationsService
from app.domain.email_thread_reply import (
    build_recipients,
    build_reply_subject,
    exclude_emails_for_reply,
    merge_cc,
    normalize_email,
    resolve_parent_id,
)
from app.domain.tenant_settings.email_recipients import (
    coerce_email_list,
    unipile_recipients_from_addresses,
)
from app.services.unipile_service import Unipile, UnipileException
from app.utils.automatic_reply_detection import (
    is_automatic_reply_email,
    strip_automatic_reply_subject_prefix,
)

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
    from_email: str | None = None,
    workflow_run_id: str | None = None,
    sent_folder_id: str | None = None,
) -> str | None:
    if not tenant_id or not isinstance(result, dict) or not result.get("success"):
        return None
    communications_service = CommunicationsService()
    return communications_service.record_outbound_from_send(
        tenant_id,
        send_result=result,
        body=body,
        subject=subject,
        thread_id=thread_id or result.get("thread_id"),
        to=to,
        cc=cc,
        bcc=bcc,
        account_id=account_id,
        from_email=from_email,
        extra_metadata=communication_metadata,
        workflow_run_id=workflow_run_id,
        sent_folder_id=sent_folder_id,
    )

# Private helpers (thread reply primitives live in app.domain.email_thread_reply)

def _normalize_email(e: Any) -> str:
    return normalize_email(e)


def _unipile_recipient_list(field: Any, *, required: bool) -> List[Dict[str, str]]:
    addrs = coerce_email_list(field, required=required)
    return unipile_recipients_from_addresses(addrs)


def _unipile_from_recipient(from_email: str | None) -> dict[str, str] | None:
    alias = (from_email or "").strip()
    if not alias:
        return None
    recipients = unipile_recipients_from_addresses([alias])
    return recipients[0] if recipients else None


def _resolve_parent_id(
    unipile: Unipile,
    latest_email: Dict,
    reply_to_message_id: Optional[str],
    account_id: Optional[str],
) -> str:
    return resolve_parent_id(unipile, latest_email, reply_to_message_id, account_id)


def _build_reply_subject(original_subject: str, override: Optional[str] = None) -> str:
    return build_reply_subject(original_subject, override)


def _build_recipients(
    latest_email: Dict,
    exclude_email: str,
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    return build_recipients(latest_email, exclude_email)


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
    return merge_cc(thread_cc, upstream_cc, exclude_email, to_recipients)


def _select_reply_anchor_email(
    emails: list[Dict],
    *,
    handle_auto_reply: bool,
) -> tuple[Dict, int]:
    """
    Pick the message to anchor reply-all recipients and subject on.

    When ``handle_auto_reply`` is true, skip automatic replies (newest first).
    """
    if not emails:
        raise UnipileException("No emails in thread to select reply anchor")

    sorted_emails = sorted(emails, key=lambda e: e.get("date") or "", reverse=True)
    if not handle_auto_reply:
        return sorted_emails[0], 0

    skipped = 0
    for email in sorted_emails:
        if is_automatic_reply_email(email):
            skipped += 1
            continue
        return email, skipped

    raise UnipileException("thread contains only automatic replies")


# Public tools


def send_unipile_thread_reply(
    thread_id: str,
    account_id: str,
    subject: str,
    body: str,
    *,
    handle_auto_reply: bool = True,
) -> bool:
    """In-thread reply via Unipile (wraps ``reply_to_thread``; returns False on failure)."""
    try:
        reply_to_thread(
            thread_id=thread_id,
            body=body,
            account_id=account_id,
            subject=subject or None,
            handle_auto_reply=handle_auto_reply,
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
    *,
    account_id: str,
    tenant_id: Optional[str] = None,
    communication_metadata: Optional[dict[str, Any]] = None,
    cc: Any = None,
    bcc: Any = None,
    workflow_run_id: Optional[str] = None,
    handle_auto_reply: bool = True,
    from_email: Optional[str] = None,
    sent_folder_id: Optional[str] = None,
):
    """
    POD request / reminder delivery. If ``thread_id`` is set, reply in thread; else if ``to``
    has at least one valid address, send a new message. Requires ``UNIPILE_API_KEY`` and a
    sending ``account_id`` (caller must resolve from tenant settings / payload).

    ``to``, ``cc``, and ``bcc`` accept a single email string or a list of strings.

    ``subject`` is optional; empty/missing values default to ``"POD Request"``.

    When ``sent_folder_id`` is set, outbound ``communications.external_id`` is enriched
    to Unipile ``deprecated_id`` (reply ``in_reply_to.id`` correlation key).
    """
    subject = subject or "POD Request"
    body = (body or "").strip() or "Please send pod"
    tid = (thread_id or "").strip()
    acc = (account_id or "").strip()
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
        raise ValueError("send_email: account_id is required")

    if tid:
        return reply_to_thread(
            thread_id=tid,
            body=body,
            account_id=acc,
            subject=subject,
            tenant_id=tenant_id,
            communication_metadata=communication_metadata,
            workflow_run_id=workflow_run_id,
            handle_auto_reply=handle_auto_reply,
            from_email=from_email,
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
    from_recipient = _unipile_from_recipient(from_email)

    unipile = Unipile()
    out = unipile.send_email(
        to=to_recipients,
        subject=subject,
        body=body,
        account_id=acc,
        cc=cc_recipients,
        bcc=bcc_recipients,
        from_recipient=from_recipient,
    )
    if not out.get("success"):
        err = out.get("error") or "Unipile send_email failed"
        logger.warning("send_email: Unipile send failed: %s", err)
        raise UnipileException(str(err))
    to_logged = coerce_email_list(to, required=False)
    cc_logged = coerce_email_list(cc, required=False)
    bcc_logged = coerce_email_list(bcc, required=False)
    comm_id = _record_outbound_communication(
        tenant_id=tenant_id,
        communication_metadata=communication_metadata,
        body=body,
        subject=subject,
        result=out,
        to=to_logged or None,
        cc=cc_logged or None,
        bcc=bcc_logged or None,
        account_id=acc,
        from_email=from_email,
        workflow_run_id=workflow_run_id,
        sent_folder_id=sent_folder_id,
    )
    if comm_id:
        out["communication_id"] = comm_id
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
    workflow_run_id: Optional[str] = None,
    handle_auto_reply: bool = True,
    from_email: Optional[str] = None,
):
    """
    Orchestrates a thread reply (reply-all):
    1. Resolve our email (to exclude from recipients)
    2. Fetch thread emails
    3. Select anchor message (skip automatic replies when handle_auto_reply)
    4. Resolve parent message id for Unipile reply_to
    5. Auto-resolve subject from anchor message (unless overridden)
    6. Build reply-all TO + CC lists
    7. Merge any upstream CC, deduplicate
    8. Send via Unipile
    """
    if not thread_id:
        raise UnipileException("thread_id is required to reply to a thread")

    unipile = Unipile()

    # 1) Resolve our email to exclude from recipients
    primary_email = unipile.get_account_email(account_id)
    exclude_email = exclude_emails_for_reply(
        primary_email=primary_email,
        from_email=from_email,
    )
    from_recipient = _unipile_from_recipient(from_email)

    # 2) Fetch all emails in thread
    emails_result = unipile.list_emails(account_id=account_id, thread_id=thread_id, limit=50)
    emails = emails_result.get("items", []) if isinstance(emails_result, dict) else []
    if not emails:
        raise UnipileException(f"No emails found for thread_id={thread_id}")

    anchor_email, skipped_auto_replies = _select_reply_anchor_email(
        emails,
        handle_auto_reply=handle_auto_reply,
    )

    # 3) Resolve parent message id
    reply_to_id = _resolve_parent_id(unipile, anchor_email, reply_to_message_id, account_id)
    logger.info("reply_to_thread: resolved reply_to_id=%s", reply_to_id)

    # 4) Subject: use anchor email's subject unless upstream overrides
    original_subject = strip_automatic_reply_subject_prefix(
        str(anchor_email.get("subject") or "")
    )
    effective_subject = _build_reply_subject(original_subject, subject)

    # 5) Reply-all: build TO and CC from anchor email
    to_list, thread_cc = _build_recipients(anchor_email, exclude_email)
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
        from_recipient=from_recipient,
    )

    result.setdefault("thread_id", thread_id)
    result.setdefault("reply_to_message_id", reply_to_id)
    if handle_auto_reply and skipped_auto_replies:
        result["skipped_auto_replies"] = skipped_auto_replies
    if not result.get("success", True):
        logger.warning(
            "reply_to_thread: Unipile send failed thread_id=%s reply_to_id=%s err=%s details=%s",
            thread_id,
            reply_to_id,
            result.get("error"),
            result.get("error_details"),
        )
    else:
        comm_id = _record_outbound_communication(
            tenant_id=tenant_id,
            communication_metadata=communication_metadata,
            body=body,
            subject=effective_subject,
            result=result,
            thread_id=thread_id,
            to=to_list,
            cc=cc_final,
            account_id=account_id,
            from_email=from_email,
            workflow_run_id=workflow_run_id,
        )
        if comm_id:
            result["communication_id"] = comm_id
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
