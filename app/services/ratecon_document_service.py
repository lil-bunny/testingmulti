"""Ratecon email attachment upload + ``documents`` persistence."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.models.document import DocumentType
from app.services.attachment_normalizer import ratecon_shipment_object_basename
from app.services.s3bucket_service import bucket
from app.tools.documents import insert_document
from app.tools.email import detect_attachment_bytes_type, get_email_attachments
from app.workflows.shipment_resolver import (
    resolve_shipment_id,
    resolve_shipments_row_id_for_db,
)

logger = get_logger(__name__)


class RateconDocumentService:
    """Upload ratecon attachments and persist ``documents`` rows."""

    def upload_email_attachments(self, data: dict[str, Any]) -> dict[str, Any]:
        """Download ratecon email attachments, upload them, and store object keys."""
        attachments = data.get("attachments") or []
        if not attachments:
            return {"skipped": True, "reason": "no_attachments"}

        email_id = data.get("email_id")
        if email_id is None or not str(email_id).strip():
            return {
                "skipped": True,
                "reason": "missing_email_id",
                "attachment_count": len(attachments),
            }

        shipment_id = resolve_shipment_id(data)
        if not shipment_id:
            out = {
                "skipped": True,
                "reason": "missing_shipment_id",
                "attachment_count": len(attachments),
            }
            logger.warning("[ratecon] S3 upload %s", out)
            return out

        shipments_row_id = resolve_shipments_row_id_for_db(data)
        account_id = data.get("account_id")
        result = self._upload_attachments_to_s3(
            email_id=str(email_id).strip(),
            account_id=str(account_id).strip() if account_id else None,
            attachments=list(attachments),
            shipment_id=str(shipment_id),
        )
        for item in result.get("results") or []:
            if not item.get("success") or not item.get("object_key"):
                item["document_persist"] = {
                    "stored": False,
                    "skipped": True,
                    "reason": "no_successful_upload_or_object_key",
                }
                continue
            if not shipments_row_id:
                item["document_persist"] = {
                    "stored": False,
                    "skipped": True,
                    "reason": "missing_shipments_row_id",
                }
                logger.warning(
                    "[ratecon] skip document persist: missing shipments_row_id shipment_id=%s",
                    shipment_id,
                )
                continue
            item["document_persist"] = insert_document(
                DocumentType.RATECON,
                str(item["object_key"]),
                shipments_row_id=shipments_row_id,
            )
        return result

    @staticmethod
    def _upload_attachments_to_s3(
        *,
        email_id: str,
        account_id: str | None,
        attachments: list[dict[str, Any]],
        shipment_id: str,
    ) -> dict[str, Any]:
        object_basename = ratecon_shipment_object_basename(shipment_id)
        folder = (settings.BUCKET_RATECON_ATTACHMENTS_FOLDER or "").strip()
        results: list[dict[str, Any]] = []

        for raw in attachments:
            if not isinstance(raw, dict):
                continue
            attachment_id = raw.get("id")
            original_filename = (
                raw.get("name") or raw.get("filename") or raw.get("file_name") or ""
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
                file_content = get_email_attachments(email_id, attachment_id, account_id)
            except Exception as exc:
                logger.exception(
                    "ratecon page count: Unipile fetch failed attachment_id=%s",
                    attachment_id,
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

            ext, content_type = detect_attachment_bytes_type(file_content)
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
                    "extension": ext,
                }
            )
        keys = [r["object_key"] for r in results if r.get("success") and r.get("object_key")]
        return {
            "results": results,
            "ratecon_object_keys": keys,
            "all_succeeded": bool(results) and all(r.get("success") for r in results),
        }
