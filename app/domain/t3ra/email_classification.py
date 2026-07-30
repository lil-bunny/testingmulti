"""T3RA Unipile inbound email classification (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.t3ra.email_attachments import (
    load_id_from_ratecon_attachment_name,
    unipile_ratecon_pdf_attachment,
)
from app.domain.unipile_email_attachments import attachment_display_name
from app.domain.unipile_email import is_unipile_email_reply

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


def extract_ratecon_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Extract ratecon correlation fields from a Unipile ``mail_received`` payload.

    Returns only keys needed for enqueue / Turvo resolve: ``load_id``, ``subject``,
    ``thread_id``. Attachment download uses root ``attachments`` + ``email_id``.
    """
    subject = str(payload.get("subject") or "").strip()

    raw_thread = payload.get("thread_id")
    thread_id = str(raw_thread).strip() or None if raw_thread else None

    empty_result = {
        "load_id": None,
        "subject": subject or None,
        "thread_id": thread_id,
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

    return {
        "load_id": load_id,
        "subject": subject or None,
        "thread_id": thread_id,
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
        """Merge ratecon metadata for Celery enqueue."""
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
