"""Detect provider automatic replies (OOO / vacation) in Unipile email objects."""

from __future__ import annotations

import re
from typing import Any

# Outlook built-in Automatic Replies use "Automatic reply: {original subject}" (en-US).
_OUTLOOK_AUTOMATIC_REPLY_SUBJECT_PREFIXES = (
    "automatic reply:",
)

_REPLY_PREFIX_RE = re.compile(
    r"^(?:(?:re|fw|fwd|aw)\s*:\s*)+",
    re.IGNORECASE,
)


def _normalize_subject_for_detection(subject: str) -> str:
    text = (subject or "").strip()
    while True:
        match = _REPLY_PREFIX_RE.match(text)
        if not match:
            break
        text = text[match.end() :].lstrip()
    return text.lower()


def is_outlook_automatic_reply(email: dict[str, Any]) -> bool:
    """True when Unipile email is Outlook built-in Automatic Replies."""
    provider = str(email.get("type") or "").strip().upper()
    if provider != "OUTLOOK":
        return False
    normalized = _normalize_subject_for_detection(str(email.get("subject") or ""))
    return any(
        normalized.startswith(prefix) for prefix in _OUTLOOK_AUTOMATIC_REPLY_SUBJECT_PREFIXES
    )


def is_automatic_reply_email(email: dict[str, Any]) -> bool:
    """Dispatch automatic-reply detection by provider (Outlook only for now)."""
    provider = str(email.get("type") or "").strip().upper()
    if provider == "OUTLOOK":
        return is_outlook_automatic_reply(email)
    return False


def strip_automatic_reply_subject_prefix(subject: str) -> str:
    """
    Remove Outlook automatic-reply subject prefix so replies use the original thread subject.

    Example: ``Re: Automatic reply: PICK UP…`` → ``PICK UP…``
    """
    text = (subject or "").strip()
    if not text:
        return text
    while True:
        match = _REPLY_PREFIX_RE.match(text)
        if not match:
            break
        text = text[match.end() :].lstrip()
    lowered = text.lower()
    for prefix in _OUTLOOK_AUTOMATIC_REPLY_SUBJECT_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return (subject or "").strip()
