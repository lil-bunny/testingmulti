"""Pure helpers for Unipile email thread reply-all (no I/O, no services)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)


def normalize_email(value: Any) -> str:
    return (str(value) if value else "").strip().lower()


def exclude_emails_for_reply(*, primary_email: str, from_email: str | None) -> str:
    """Email to exclude from reply-all TO/CC; alias takes precedence when set."""
    alias = (from_email or "").strip()
    if alias:
        return alias
    return primary_email


def attendee_to_recipient(att: Any) -> dict[str, str] | None:
    if not isinstance(att, dict):
        return None
    ident = att.get("identifier")
    if not ident or "@" not in str(ident):
        return None
    return {
        "identifier": str(ident),
        "display_name": att.get("display_name") or str(ident).split("@")[0],
    }


def resolve_parent_id(
    unipile: Unipile,
    latest_email: dict[str, Any],
    reply_to_message_id: str | None,
    account_id: str | None,
) -> str:
    if reply_to_message_id:
        reply_to_message_id = str(reply_to_message_id).strip()
        if not reply_to_message_id:
            raise UnipileException("reply_to_message_id was provided but empty")

        resolved = None
        try:
            resolved = unipile.get_email(reply_to_message_id, account_id=account_id)
        except Exception:
            logger.warning(
                "resolve_parent_id: could not resolve provider_id=%s, using as-is",
                reply_to_message_id,
            )

        reply_to_id = (
            (resolved.get("id") if isinstance(resolved, dict) else None)
            or reply_to_message_id
        )
        return str(reply_to_id).strip()

    pid = (
        latest_email.get("id")
        or latest_email.get("provider_id")
        or latest_email.get("message_id")
    )
    if not pid:
        raise UnipileException(
            "Could not determine parent message id to reply to; "
            "pass reply_to_message_id explicitly"
        )
    return str(pid).strip()


def build_reply_subject(original_subject: str, override: str | None = None) -> str:
    subj = (
        original_subject.strip()
        if original_subject and original_subject.strip()
        else None
    )
    if not subj and override:
        subj = str(override).strip() or None
    if not subj:
        raise UnipileException("No subject found in thread and no override provided")

    low = subj.lstrip().lower()
    if low.startswith(("re:", "re :")):
        return subj
    return f"Re: {subj}"


def build_recipients(
    latest_email: dict[str, Any],
    exclude_email: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    excluded: set[str] = set()
    if exclude_email:
        excluded.add(normalize_email(exclude_email))

    to_list: list[dict[str, str]] = []
    cc_list: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(recipient: dict[str, str] | None, target: list[dict[str, str]]) -> None:
        if not recipient or not recipient.get("identifier"):
            return
        norm = normalize_email(recipient["identifier"])
        if norm in excluded or norm in seen:
            return
        seen.add(norm)
        target.append(recipient)

    role = latest_email.get("role")
    from_attendee = latest_email.get("from_attendee")
    to_attendees = latest_email.get("to_attendees") or []
    cc_attendees = latest_email.get("cc_attendees") or []

    if role != "sent":
        _add(attendee_to_recipient(from_attendee), to_list)

    for att in to_attendees:
        _add(attendee_to_recipient(att), to_list)

    for att in cc_attendees:
        _add(attendee_to_recipient(att), cc_list)

    return to_list, cc_list


def merge_cc(
    thread_cc: list[dict[str, str]],
    upstream_cc: list[dict[str, Any]] | None,
    exclude_email: str,
    to_recipients: list[dict[str, str]],
) -> list[dict[str, str]] | None:
    excluded = {normalize_email(exclude_email)} if exclude_email else set()
    to_norm = {normalize_email(r.get("identifier")) for r in to_recipients}
    seen = {normalize_email(c.get("identifier")) for c in thread_cc}

    merged = list(thread_cc)

    for c in upstream_cc or []:
        if not isinstance(c, dict):
            continue
        ident = c.get("identifier") or c.get("email") or c.get("email_address")
        if not ident or not isinstance(ident, str) or "@" not in ident:
            continue
        norm = normalize_email(ident)
        if norm in excluded or norm in to_norm or norm in seen:
            continue
        seen.add(norm)
        merged.append(
            {
                "identifier": ident,
                "display_name": c.get("display_name") or ident.split("@")[0],
            }
        )

    return merged or None
