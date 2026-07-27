"""Cache ratecon PDF page count for the POD strip pipeline (no S3).

Downloads Unipile attachments in-memory, counts PDF pages, and upserts a
``ratecon_extraction`` ``document_analysis`` row with ``metadata.page_count``.
"""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.models.document_analysis import DocumentAnalysisType
from app.tools.document_analysis import upsert_document_analysis
from app.tools.email import detect_attachment_bytes_type, get_email_attachments
from app.tools.pdf_page_text_extractor import pdf_page_count
from app.workflows.shipment_resolver import resolve_shipments_row_id_for_db

logger = get_logger(__name__)


class RateconDocumentService:
    """Derive and persist ratecon page count (R) for later POD strip."""

    def cache_from_email_attachments(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Download ratecon email attachments and cache PDF page count.

        Skips when attachments/email_id/shipments_row_id are missing. On success
        upserts ``document_analysis`` (``ratecon_extraction``) with page_count only.
        """
        attachments = data.get("attachments") or []
        if not attachments:
            return {"success": False, "skipped": True, "reason": "no_attachments"}

        email_id = data.get("email_id")
        if email_id is None or not str(email_id).strip():
            return {
                "success": False,
                "skipped": True,
                "reason": "missing_email_id",
                "attachment_count": len(attachments),
            }

        shipments_row_id = resolve_shipments_row_id_for_db(data)
        if not shipments_row_id:
            out = {
                "success": False,
                "skipped": True,
                "reason": "missing_shipments_row_id",
                "attachment_count": len(attachments),
            }
            logger.warning("[ratecon] page count cache skipped %s", out)
            return out

        account_id = data.get("account_id")
        counted = self._count_pdf_pages_from_attachments(
            email_id=str(email_id).strip(),
            account_id=str(account_id).strip() if account_id else None,
            attachments=list(attachments),
        )
        page_count = counted.get("page_count")
        if not isinstance(page_count, int) or page_count < 1:
            return {
                "success": False,
                "skipped": False,
                "reason": counted.get("reason") or "no_pdf_page_count",
                "results": counted.get("results") or [],
            }

        persist = upsert_document_analysis(
            shipments_row_id,
            DocumentAnalysisType.RATECON_EXTRACTION,
            results={"source": "ratecon_page_count"},
            page_count=page_count,
        )
        if not persist.get("stored"):
            return {
                "success": False,
                "skipped": False,
                "reason": persist.get("error") or "document_analysis_upsert_failed",
                "page_count": page_count,
                "results": counted.get("results") or [],
                "document_analysis": persist,
            }

        return {
            "success": True,
            "skipped": False,
            "page_count": page_count,
            "results": counted.get("results") or [],
            "document_analysis": persist,
        }

    @staticmethod
    def _count_pdf_pages_from_attachments(
        *,
        email_id: str,
        account_id: str | None,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        best_page_count: int | None = None

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
                        "page_count": None,
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
                        "page_count": None,
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
                        "page_count": None,
                        "error_message": "empty attachment body",
                        "original_filename": original_filename or None,
                    }
                )
                continue

            ext, content_type = detect_attachment_bytes_type(file_content)
            if ext != "pdf" and not str(content_type or "").lower().endswith("pdf"):
                results.append(
                    {
                        "attachment_id": attachment_id,
                        "success": False,
                        "page_count": None,
                        "error_message": "not_a_pdf",
                        "original_filename": original_filename or None,
                        "content_type": content_type,
                        "extension": ext,
                    }
                )
                continue

            try:
                count = pdf_page_count(file_content)
            except Exception as exc:
                logger.exception(
                    "ratecon page count: pdf_page_count failed attachment_id=%s",
                    attachment_id,
                )
                results.append(
                    {
                        "attachment_id": attachment_id,
                        "success": False,
                        "page_count": None,
                        "error_message": str(exc),
                        "original_filename": original_filename or None,
                        "content_type": content_type,
                        "extension": ext,
                    }
                )
                continue

            if count < 1:
                results.append(
                    {
                        "attachment_id": attachment_id,
                        "success": False,
                        "page_count": count,
                        "error_message": "pdf_page_count_lt_1",
                        "original_filename": original_filename or None,
                        "content_type": content_type,
                        "extension": ext,
                    }
                )
                continue

            results.append(
                {
                    "attachment_id": attachment_id,
                    "success": True,
                    "page_count": count,
                    "error_message": None,
                    "original_filename": original_filename or None,
                    "content_type": content_type,
                    "extension": ext,
                }
            )
            if best_page_count is None or count > best_page_count:
                best_page_count = count

        if best_page_count is None:
            return {
                "page_count": None,
                "reason": "no_pdf_page_count",
                "results": results,
            }
        return {"page_count": best_page_count, "results": results}
