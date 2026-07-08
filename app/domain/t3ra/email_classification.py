"""T3RA Unipile inbound email classification (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.t3ra.email_attachments import (
    load_id_from_ratecon_attachment_name,
    unipile_ratecon_pdf_attachment,
)
from app.domain.unipile_email_attachments import attachment_display_name
from app.domain.unipile_email import (
    build_unipile_attachment_fetch_context,
    extract_email_attachment_metadata,
    is_unipile_email_reply,
)

_RATE_CONFIRMATION_SUBJECT_SNIPPET = "rate confirmation"
_TONU_SUBJECT_SNIPPET = "tonu"
_REVISED_SUBJECT_SNIPPET = "revised"


def has_rate_confirmation_subject(subject: str) -> bool:
    normalized = (subject or "").lower()
    if _TONU_SUBJECT_SNIPPET in normalized:
        return False
    if _REVISED_SUBJECT_SNIPPET in normalized:
        return False
    return _RATE_CONFIRMATION_SUBJECT_SNIPPET in normalized


def _get_attachment_uri(attachment: dict[str, Any]) -> str | None:
    """Best-effort HTTP URL if Unipile includes one (raw ``mail_received`` webhooks usually do not)."""
    for key in (
        "url",
        "uri",
        "download_url",
        "attachment_url",
        "link",
        "href",
        "public_url",
        "file_url",
    ):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def extract_ratecon_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Classify a Unipile ``mail_received``-style webhook dict for ratecon attachment metadata.

    Unipile attachments are typically ``id``, ``name``, ``mime``, ``extension``, ``size`` — not a
    download URL. Use ``unipile_attachment_fetch`` (email_id, account_id, attachment_id) with the
    Unipile API to retrieve bytes. ``attachment_uri`` is set only when the payload includes a URL.
    Root-level ``thread_id`` is echoed for workflow correlation when present.
    """
    subject = str(payload.get("subject") or "").strip()

    raw_thread = payload.get("thread_id")
    thread_id = str(raw_thread).strip() or None if raw_thread else None

    empty_result = {
        "is_ratecon_mail": False,
        "load_id": None,
        "subject": subject or None,
        "thread_id": thread_id,
        "ratecon_attachment_name": None,
        "ratecon_attachment_uri": None,
        "ratecon_attachment_id": None,
        "ratecon_attachment_mime": None,
        "ratecon_attachment_unipile": None,
        "ratecon_unipile_attachment_fetch": None,
    }

    if not has_rate_confirmation_subject(subject):
        return empty_result

    ratecon_attachment = unipile_ratecon_pdf_attachment(payload)
    if ratecon_attachment is None:
        return empty_result

    ratecon_attachment_name = attachment_display_name(ratecon_attachment)
    load_id = load_id_from_ratecon_attachment_name(ratecon_attachment_name)
    if not load_id:
        return empty_result

    attachment_metadata = extract_email_attachment_metadata(ratecon_attachment)
    attachment_fetch_context = build_unipile_attachment_fetch_context(
        payload, ratecon_attachment
    )

    return {
        "is_ratecon_mail": True,
        "load_id": load_id,
        "subject": subject or None,
        "thread_id": thread_id,
        "ratecon_attachment_name": ratecon_attachment_name,
        "ratecon_attachment_uri": _get_attachment_uri(ratecon_attachment),
        "ratecon_attachment_id": attachment_metadata.get("id"),
        "ratecon_attachment_mime": attachment_metadata.get("mime"),
        "ratecon_attachment_unipile": attachment_metadata or None,
        "ratecon_unipile_attachment_fetch": attachment_fetch_context or None,
    }


@dataclass(frozen=True)
class T3raInboundEmailClassification:
    """
    Pure classification from payload shape — no DB, no Turvo.

    ``workflow_name`` is ``None`` without rate-confirmation subject or attachments.
    Driver-details routing uses ``is_thread_reply`` separately in ingress (not ``workflow_name``).
    """

    is_rate_confirmation_subject: bool
    has_attachments: bool
    is_in_reply_to: bool
    is_thread_reply: bool
    workflow_name: str | None
    ratecon_metadata: dict[str, Any] | None
    ratecon_attachment: dict[str, Any] | None

    def to_ratecon_enqueue_payload(self) -> dict[str, Any]:
        """Merge ratecon metadata for Celery enqueue (same keys as legacy classifier dict)."""
        return {
            "workflow_name": "ratecon",
            **(self.ratecon_metadata or {}),
        }


def classify_t3ra_inbound_email(payload: dict[str, Any]) -> T3raInboundEmailClassification:
    """
    Classify incoming email webhook into a T3RA workflow candidate.

    Priority encoded in ingress, not here:
      1. rate-confirmation + attachments + ``in_reply_to`` → ``pod_lifecycle``
      2. thread reply (driver-details) — separate ingress check
      3. rate-confirmation + attachments + new mail → ``ratecon``
    """
    subject = str(payload.get("subject") or "").strip()
    is_rate_confirmation = has_rate_confirmation_subject(subject)
    has_attachments = bool(payload.get("has_attachments"))
    is_in_reply_to = bool(payload.get("in_reply_to"))
    is_thread_reply = is_unipile_email_reply(payload)

    if not is_rate_confirmation or not has_attachments:
        return T3raInboundEmailClassification(
            is_rate_confirmation_subject=is_rate_confirmation,
            has_attachments=has_attachments,
            is_in_reply_to=is_in_reply_to,
            is_thread_reply=is_thread_reply,
            workflow_name=None,
            ratecon_metadata=None,
            ratecon_attachment=None,
        )

    if is_in_reply_to:
        return T3raInboundEmailClassification(
            is_rate_confirmation_subject=True,
            has_attachments=True,
            is_in_reply_to=True,
            is_thread_reply=is_thread_reply,
            workflow_name="pod_lifecycle",
            ratecon_metadata=None,
            ratecon_attachment=None,
        )

    ratecon_metadata = extract_ratecon_metadata_from_payload(payload)
    ratecon_attachment = unipile_ratecon_pdf_attachment(payload)

    return T3raInboundEmailClassification(
        is_rate_confirmation_subject=True,
        has_attachments=True,
        is_in_reply_to=False,
        is_thread_reply=is_thread_reply,
        workflow_name="ratecon",
        ratecon_metadata=ratecon_metadata,
        ratecon_attachment=ratecon_attachment,
    )


def classify_workflow_type(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Legacy dict shape for callers expecting ``workflow_name`` + ratecon metadata keys."""
    email_classification = classify_t3ra_inbound_email(payload)
    if email_classification.workflow_name is None:
        return None
    if email_classification.workflow_name == "pod_lifecycle":
        return {"workflow_name": "pod_lifecycle"}
    return email_classification.to_ratecon_enqueue_payload()
