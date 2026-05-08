import re
from pathlib import Path
from typing import Any, Optional

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


def _build_unipile_attachment_fetch_context(
    payload: dict[str, Any], attachment: dict[str, Any]
) -> dict[str, str]:
    """IDs needed for Unipile ``get_email_attachment`` / download APIs (webhook has no file URL)."""
    fetch_context: dict[str, str] = {}
    email_id = payload.get("email_id")
    if email_id is not None and str(email_id).strip():
        fetch_context["email_id"] = str(email_id).strip()
    account_id = payload.get("account_id")
    if account_id is not None and str(account_id).strip():
        fetch_context["account_id"] = str(account_id).strip()
    attachment_id = attachment.get("id")
    if attachment_id is not None and str(attachment_id).strip():
        fetch_context["attachment_id"] = str(attachment_id).strip()
    return fetch_context


def _extract_unipile_attachment_metadata(attachment: dict[str, Any]) -> dict[str, Any]:
    """Subset of Unipile attachment object (``id``, ``name``, ``mime``, ``extension``, ``size``)."""
    if not isinstance(attachment, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in ("id", "name", "mime", "extension", "size"):
        if key not in attachment:
            continue
        value = attachment.get(key)
        if value is None:
            continue
        if key == "size":
            try:
                metadata[key] = int(value)
            except (TypeError, ValueError):
                metadata[key] = value
        else:
            text_value = str(value).strip()
            if text_value:
                metadata[key] = text_value
    return metadata


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

    attachment_metadata = _extract_unipile_attachment_metadata(matching_attachment)
    attachment_fetch_context = _build_unipile_attachment_fetch_context(payload, matching_attachment)

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


class WorkflowClassifierService:
    def extract_ratecon_metadata_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return extract_ratecon_metadata_from_payload(payload)

    def has_rate_confirmation_subject(self, subject: str) -> bool:
        return has_rate_confirmation_subject(subject)

    def classify_workflow_type(payload: dict[str, Any]) -> dict[str, Any] | None:
        """
        Classify incoming email webhook into a workflow.
            1. "rate confirmation" keyword in subject
            2. has_attachments is true
            3.1 new email : in_reply_to doesn't exist
                trigger ratecon workflow
            3.2 reply email : in_reply_to exists
                trigger pod reply workflow
        """
        

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
