import re
from pathlib import Path
from typing import Any, Optional

from app.core.logger import get_logger
from app.domain.unipile_email import (
    build_unipile_attachment_fetch_context,
    extract_email_attachment_metadata,
)
from app.repositories.tenants_db_repository import find_tenant_id_by_settings_email_webhook_name
logger = get_logger(__name__)


_RATE_CONFIRMATION_SUBJECT_SNIPPET = "rate confirmation"
_CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET = "carrier_rate_confirmation"

def _get_attachment_display_filename(attachment: Any) -> str:
    """Resolve Unipile 
     display name (``name`` / ``filename`` / ``file_name``)."""
    if not isinstance(attachment, dict):
        return ""
    for key in ("name", "filename", "file_name"):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def unipile_primary_attachment_file_name(payload: dict[str, Any]) -> Optional[str]:
    """
    Filename for generic Unipile ``mail_received`` bodies: first attachment with a display
    name, else top-level ``file_name`` / ``filename``.
    """
    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            display = _get_attachment_display_filename(attachment)
            if display:
                return display
    for key in ("file_name", "filename"):
        raw = payload.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _is_pdf_attachment(attachment: dict, filename: str) -> bool:
    mime = str(attachment.get("mime") or attachment.get("content_type") or "").lower()
    if mime == "application/pdf":
        return True
    return filename.lower().endswith(".pdf")


def _get_attachment_uri(attachment: dict) -> Optional[str]:
    """Best-effort HTTP URL if Unipile includes one (raw ``mail_received`` webhooks usually do not)."""
    if not isinstance(attachment, dict):
        return None
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


def _extract_load_id_from_attachment_name(filename: str) -> Optional[str]:
    """Take last contiguous digit run from basename stem (tweak if filenames gain extra trailing digits)."""
    stem = Path(filename).stem
    runs = re.findall(r"\d+", stem)
    if not runs:
        return None
    return runs[-1]


def extract_ratecon_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Classify a Unipile ``mail_received``-style webhook dict.

    Unipile attachments are typically ``id``, ``name``, ``mime``, ``extension``, ``size`` — not a
    download URL. Use ``unipile_attachment_fetch`` (email_id, account_id, attachment_id) with the
    Unipile API to retrieve bytes. ``attachment_uri`` is set only when the payload includes a URL.
    Root-level ``thread_id`` is echoed for workflow correlation when present.
    """
    subject = str(payload.get("subject") or "").strip()
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        attachments = []

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

    matching_attachment: Optional[dict] = None
    matching_attachment_name: Optional[str] = None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_name = _get_attachment_display_filename(attachment)
        if not attachment_name:
            continue
        if _CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET not in attachment_name.lower():
            continue
        if not _is_pdf_attachment(attachment, attachment_name):
            continue
        matching_attachment = attachment
        matching_attachment_name = attachment_name
        break

    if not matching_attachment_name or matching_attachment is None:
        return empty_result

    load_id = _extract_load_id_from_attachment_name(matching_attachment_name)
    if not load_id:
        return empty_result

    attachment_metadata = extract_email_attachment_metadata(matching_attachment)
    attachment_fetch_context = build_unipile_attachment_fetch_context(payload, matching_attachment)

    return {
        "is_ratecon_mail": True,
        "load_id": load_id,
        "subject": subject or None,
        "thread_id": thread_id,
        "ratecon_attachment_name": matching_attachment_name,
        "ratecon_attachment_uri": _get_attachment_uri(matching_attachment),
        "ratecon_attachment_id": attachment_metadata.get("id"),
        "ratecon_attachment_mime": attachment_metadata.get("mime"),
        "ratecon_attachment_unipile": attachment_metadata or None,
        "ratecon_unipile_attachment_fetch": attachment_fetch_context or None,
    }

def has_rate_confirmation_subject(subject: str) -> bool:
    return _RATE_CONFIRMATION_SUBJECT_SNIPPET in (subject or "").lower()


def _normalize_attachment_extension(value: Any) -> str:
    return str(value or "").strip().lower().lstrip(".")


def email_first_attachment(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """First attachment dict that has an ``id`` (any file type), in list order."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("id") is not None and str(attachment.get("id")).strip():
            return attachment
    return None


def unipile_first_attachment_by_extension(
    payload: dict[str, Any], extension: str
) -> Optional[dict[str, Any]]:
    """First attachment whose ``extension`` matches (e.g. ``\"xlsx\"``), after normalization."""
    want = _normalize_attachment_extension(extension)
    if not want:
        return None
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        ext = _normalize_attachment_extension(attachment.get("extension"))
        if ext == want:
            return attachment
    return None


def _is_load_tendering_unipile(payload: dict[str, Any]) -> bool:
    """
    Load tendering when Unipile ``webhook_name`` maps to ``tenants.settings.email_webhook_name``
    and the payload carries a qualifying .xlsx attachment.
    """
    webhook_name = str(payload.get("webhook_name") or "").strip()
    if not webhook_name:
        return False
    if not find_tenant_id_by_settings_email_webhook_name(webhook_name):
        return False
    if not payload.get("has_attachments"):
        return False
    if not isinstance(payload.get("attachments"), list):
        return False
    return unipile_first_attachment_by_extension(payload, "xlsx") is not None


class WorkflowClassifierService:
    def extract_ratecon_metadata_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return extract_ratecon_metadata_from_payload(payload)

    def has_rate_confirmation_subject(self, subject: str) -> bool:
        return has_rate_confirmation_subject(subject)

    def classify_workflow_type(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        Classify incoming email webhook into a workflow.
            1. "rate confirmation" keyword in subject
            2. has_attachments is true
            3.1 new email : in_reply_to doesn't exist
                trigger ratecon workflow
            3.2 reply email : in_reply_to exists
                trigger pod reply workflow
        """

        if _is_load_tendering_unipile(payload):
            logger.info(
                "Load tendering workflow triggered webhook_name=%r",
                payload.get("webhook_name"),
            )
            return {"workflow_name": "load_tendering"}

        subject = str(payload.get("subject") or "").strip()
        if not has_rate_confirmation_subject(subject):
            return None

        if not payload.get("has_attachments"):
            return None

        if payload.get("in_reply_to"):
            return {
                "workflow_name": "pod_lifecycle",
            }

        return {
            "workflow_name": "ratecon",
            **extract_ratecon_metadata_from_payload(payload),
        }
