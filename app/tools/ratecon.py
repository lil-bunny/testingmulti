"""Rate confirmation helpers (plain args; no LangGraph state)."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.services.attachment_normalizer import ratecon_shipment_object_basename
from app.services.s3bucket_service import bucket
from app.tools.email import detect_attachment_bytes_type, get_email_attachments

logger = get_logger(__name__)


def upload_ratecon_email_attachments_to_s3(
    *,
    email_id: str,
    account_id: str | None,
    attachments: list[dict[str, Any]],
    shipment_id: str,
) -> dict[str, Any]:
    """
    For each Unipile attachment id in ``attachments``, fetch bytes and upload to S3.

    Uses ``settings.BUCKET_RATECON_ATTACHMENTS_FOLDER`` as the upload folder and
    ``ratecon_shipment_object_basename`` (``ratecon_{shipmentId}.pdf``) for the object name.
    """
    ship_token = (shipment_id or "").strip() or "unknown"
    object_basename = ratecon_shipment_object_basename(ship_token)
    folder = (
        (settings.BUCKET_RATECON_ATTACHMENTS_FOLDER or "").strip() or "ratecon_attachments"
    )
    results: list[dict[str, Any]] = []

    meta_by_id = {str(a.get("id")): a for a in attachments if isinstance(a, dict) and a.get("id") is not None}

    for raw in attachments:
        if not isinstance(raw, dict):
            continue
        attachment_id = raw.get("id")
        meta = meta_by_id.get(str(attachment_id), raw) if attachment_id is not None else raw
        original_filename = (
            (meta.get("name") or meta.get("filename") or meta.get("file_name") or "")
            if isinstance(meta, dict)
            else ""
        )
        if attachment_id is None:
            results.append(
                {
                    "attachment_id": None,
                    "success": False,
                    "object_key": None,
                    "error_message": "missing attachment id",
                    "original_filename": original_filename or None,
                }
            )
            continue

        try:
            file_content = get_email_attachments(
                email_id,
                attachment_id,
                account_id,
            )
        except Exception as exc:
            logger.exception(
                "ratecon S3: Unipile fetch failed attachment_id=%s", attachment_id
            )
            results.append(
                {
                    "attachment_id": attachment_id,
                    "success": False,
                    "object_key": None,
                    "error_message": str(exc),
                    "original_filename": original_filename or None,
                }
            )
            continue

        if not file_content:
            results.append(
                {
                    "attachment_id": attachment_id,
                    "success": False,
                    "object_key": None,
                    "error_message": "empty attachment body",
                    "original_filename": original_filename or None,
                }
            )
            continue

        _ext, content_type = detect_attachment_bytes_type(file_content)
        upload_result = bucket.upload_file(
            file_content=file_content,
            filename=object_basename,
            content_type=content_type,
            folder=folder,
        )
        object_key = upload_result.get("object_key") if upload_result.get("success") else None
        results.append(
            {
                "attachment_id": attachment_id,
                "success": bool(upload_result.get("success")),
                "object_key": object_key,
                "error_message": upload_result.get("error_message"),
                "original_filename": original_filename or None,
                "content_type": content_type,
                "extension": _ext,
            }
        )

    keys = [r["object_key"] for r in results if r.get("success") and r.get("object_key")]
    return {
        "results": results,
        "ratecon_object_keys": keys,
        "all_succeeded": bool(results) and all(r.get("success") for r in results),
    }
