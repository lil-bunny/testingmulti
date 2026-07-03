"""Ratecon email attachment upload + LLM analysis (service → repository / integrations)."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.services.attachment_normalizer import (
    _sanitize_path_segment,
    ratecon_shipment_object_basename,
)
from app.services.ratecon_extraction import extract_from_pdf_path
from app.services.s3bucket_service import bucket, normalize_object_key
from app.tools.email import detect_attachment_bytes_type, get_email_attachments
from app.workflows.shipment_resolver import (
    resolve_shipment_id,
    resolve_shipments_row_id_for_db,
)

logger = get_logger(__name__)

_SOFT_ANALYSIS_ERRORS = frozenset(
    {
        "extraction_empty",
        "s3_download_failed",
        "downloaded_file_not_pdf",
    }
)


def _uuid_or_none(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _document_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stored": True,
        "id": str(row["id"]),
        "type": str(row["type"]),
        "shipment_id": row["shipment_id"],
        "storage_key": row["storage_key"],
        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        "created_at": row["created_at"],
    }


def _is_soft_analysis_failure(out: dict[str, Any]) -> bool:
    if out.get("skipped"):
        return True
    if out.get("success"):
        return not bool(out.get("findings"))
    err = str(out.get("error") or "").strip()
    return err in _SOFT_ANALYSIS_ERRORS


class RateconDocumentService:
    """Upload ratecon PDFs and run optional LLM extraction for the ratecon workflow."""

    def upload_email_attachments(self, data: dict[str, Any]) -> dict[str, Any]:
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

        account_id = data.get("account_id")
        result = self._upload_attachments_to_s3(
            email_id=str(email_id).strip(),
            account_id=str(account_id).strip() if account_id else None,
            attachments=list(attachments),
            shipment_id=str(shipment_id),
        )

        shipments_row_id = resolve_shipments_row_id_for_db(data)
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
            item["document_persist"] = self._persist_ratecon_document(
                storage_key=str(item["object_key"]),
                shipments_row_id=shipments_row_id,
            )
        return result

    def analyze_and_persist(self, data: dict[str, Any]) -> dict[str, Any]:
        sid = resolve_shipment_id(data)
        if not sid:
            out = {"success": False, "error": "missing_shipment_id"}
            logger.error("ratecon analysis: missing_shipment_id")
            return {"ratecon_analysis_results": out}

        shipments_row_id = resolve_shipments_row_id_for_db(data)
        if not shipments_row_id:
            out = {"success": False, "error": "missing_shipments_row_id", "shipment_id": sid}
            logger.error("ratecon analysis: missing_shipments_row_id shipment_id=%s", sid)
            return {"ratecon_analysis_results": out}

        analysis_out = self._run_analysis(
            data=data,
            shipment_id=sid,
            shipments_row_id=shipments_row_id,
        )
        patch: dict[str, Any] = {"ratecon_analysis_results": analysis_out}

        if _is_soft_analysis_failure(analysis_out):
            logger.warning(
                "ratecon analysis soft-fail shipment_id=%s error=%s skipped=%s",
                sid,
                analysis_out.get("error"),
                analysis_out.get("skipped"),
            )
            return patch

        if not analysis_out.get("success") or not analysis_out.get("findings"):
            return patch

        persist = self._persist_ratecon_analysis(
            shipments_row_id=shipments_row_id,
            findings=analysis_out["findings"],
            confidence_score=analysis_out.get("confidence_score"),
            document_id=analysis_out.get("document_id"),
        )
        patch["document_analysis_ratecon"] = persist
        return patch

    @staticmethod
    def _upload_attachments_to_s3(
        *,
        email_id: str,
        account_id: str | None,
        attachments: list[dict[str, Any]],
        shipment_id: str,
    ) -> dict[str, Any]:
        ship_token = (shipment_id or "").strip() or "unknown"
        object_basename = ratecon_shipment_object_basename(ship_token)
        folder = (settings.BUCKET_RATECON_ATTACHMENTS_FOLDER or "").strip()
        results: list[dict[str, Any]] = []

        meta_by_id = {
            str(a.get("id")): a
            for a in attachments
            if isinstance(a, dict) and a.get("id") is not None
        }

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
                file_content = get_email_attachments(email_id, attachment_id, account_id)
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

    def _persist_ratecon_document(
        self,
        *,
        storage_key: str,
        shipments_row_id: str,
    ) -> dict[str, Any]:
        if not storage_key:
            return {"stored": False, "id": None, "error": "missing_storage_key"}

        try:
            key = normalize_object_key(storage_key)
        except ValueError as exc:
            return {"stored": False, "id": None, "error": str(exc)}

        row_shipment_id = _uuid_or_none(shipments_row_id)
        if not row_shipment_id:
            return {"stored": False, "id": None, "error": "invalid_shipments_row_id"}

        doc_id = str(uuid.uuid4())

        def _write(repos: Any) -> dict[str, Any]:
            row = repos.documents.upsert_by_storage_key(
                id=doc_id,
                doc_type=DocumentType.RATECON.value,
                shipment_id=row_shipment_id,
                storage_key=key,
            )
            if not row:
                return {"stored": False, "id": None, "error": "insert_returned_no_row"}
            return _document_row_payload(row)

        try:
            return run_with_repos(_write)
        except Exception as exc:
            logger.exception(
                "ratecon document persist failed shipments_row_id=%s",
                row_shipment_id,
            )
            return {"stored": False, "id": None, "error": str(exc)}

    def _read_ratecon_document(self, shipments_row_id: str) -> dict[str, Any]:
        row_shipment_id = _uuid_or_none(shipments_row_id)
        if not row_shipment_id:
            return {
                "found": False,
                "error": "invalid_shipments_row_id",
            }

        def _read(repos: Any) -> dict[str, Any] | None:
            return repos.documents.find_latest_by_shipment_and_type(
                shipment_id=row_shipment_id,
                doc_type=DocumentType.RATECON.value,
            )

        try:
            row = run_with_repos(_read)
        except Exception as exc:
            logger.exception(
                "ratecon read document failed shipments_row_id=%s",
                row_shipment_id,
            )
            return {"found": False, "error": str(exc)}

        if not row:
            return {"found": False, "error": None}

        meta = row.get("metadata")
        return {
            "found": True,
            "id": str(row["id"]),
            "storage_key": row["storage_key"],
            "shipment_id": row_shipment_id,
            "type": DocumentType.RATECON.value,
            "metadata": meta if isinstance(meta, dict) else None,
            "created_at": row.get("created_at"),
            "error": None,
        }

    def _run_analysis(
        self,
        *,
        data: dict[str, Any],
        shipment_id: str,
        shipments_row_id: str,
    ) -> dict[str, Any]:
        doc = self._read_ratecon_document(shipments_row_id)
        if doc.get("error"):
            return {
                "success": False,
                "error": doc["error"],
                "shipment_id": shipment_id,
            }

        if not doc.get("found") or not doc.get("storage_key"):
            logger.info(
                "ratecon analysis: no ratecon document row for shipment_id=%s",
                shipment_id,
            )
            return {
                "success": True,
                "skipped": True,
                "reason": "no_ratecon_document_in_db",
                "shipment_id": shipment_id,
            }

        raw_key = doc["storage_key"]
        try:
            object_key = normalize_object_key(raw_key)
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "shipment_id": shipment_id,
                "ratecon_object_key": raw_key,
            }

        document_id = doc.get("id")
        expected_key = f"ratecon_{_sanitize_path_segment(shipment_id)}.pdf"
        if expected_key.lower() not in (object_key or "").lower():
            logger.warning(
                "ratecon analysis: object key missing expected basename %r (shipment_id=%s)",
                expected_key,
                shipment_id,
            )

        tmp_path: str | None = None
        try:
            dl = bucket.download_object_bytes(object_key)
            if not dl.get("success"):
                return {
                    "success": False,
                    "error": dl.get("error_message") or "s3_download_failed",
                    "shipment_id": shipment_id,
                    "ratecon_object_key": object_key,
                }
            body = dl["body"]
            if not body.startswith(b"%PDF"):
                return {
                    "success": False,
                    "error": "downloaded_file_not_pdf",
                    "shipment_id": shipment_id,
                    "ratecon_object_key": object_key,
                }

            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            try:
                os.write(fd, body)
            finally:
                os.close(fd)

            page_results, extracted = extract_from_pdf_path(
                tmp_path,
                model_label=settings.LLM_MODEL or "",
                tenant_settings=data.get("tenant_settings"),
            )
            good_pages = sum(1 for p in page_results if p.get("extracted_data"))
            has_ids = bool(extracted.get("shipment_identifiers")) or bool(
                extracted.get("primary_identifier")
            )
            if not has_ids and good_pages == 0:
                return {
                    "success": False,
                    "error": "extraction_empty",
                    "shipment_id": shipment_id,
                    "ratecon_object_key": object_key,
                    "page_results": page_results,
                    "extracted_data": extracted,
                }

            findings = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "pages_processed": len(page_results),
                    "successful_pages": good_pages,
                    "failed_pages": len(page_results) - good_pages,
                    "model": settings.LLM_MODEL,
                    "total_identifiers_found": len(extracted.get("shipment_identifiers") or []),
                    "identifiers_list": extracted.get("shipment_identifiers") or [],
                },
                "extracted_fields": extracted,
                "page_details": page_results,
            }
            id_count = len(extracted.get("shipment_identifiers") or [])
            confidence = 1.0 if id_count else 0.25

            return {
                "success": True,
                "shipment_id": shipment_id,
                "ratecon_object_key": object_key,
                "ratecon_document_id": document_id,
                "primary_identifier": extracted.get("primary_identifier"),
                "identifiers_found": extracted.get("shipment_identifiers"),
                "findings": findings,
                "document_id": document_id,
                "confidence_score": confidence,
            }
        except Exception as exc:
            logger.exception("ratecon analysis failed shipment_id=%s", shipment_id)
            return {
                "success": False,
                "error": str(exc),
                "shipment_id": shipment_id,
                "ratecon_object_key": object_key,
            }
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _persist_ratecon_analysis(
        self,
        *,
        shipments_row_id: str,
        findings: dict[str, Any],
        confidence_score: float | None,
        document_id: str | None,
    ) -> dict[str, Any]:
        row_shipment_id = _uuid_or_none(shipments_row_id)
        if not row_shipment_id:
            return {"stored": False, "id": None, "error": "invalid_shipments_row_id"}

        row_document_id = _uuid_or_none(document_id) if document_id else None
        if document_id and not row_document_id:
            return {"stored": False, "id": None, "error": "invalid_document_id"}

        row_id = str(uuid.uuid4())
        llm_model = {"model": settings.LLM_MODEL} if settings.LLM_MODEL else None

        def _write(repos: Any) -> dict[str, Any]:
            row = repos.document_analysis.upsert_by_shipment_and_type(
                id=row_id,
                shipment_id=row_shipment_id,
                analysis_type=DocumentAnalysisType.RATECON_EXTRACTION.value,
                results=findings,
                confidence_score=confidence_score,
                llm_model=llm_model,
                document_id=row_document_id,
            )
            if not row:
                return {"stored": False, "id": None, "error": "upsert_returned_no_row"}
            return {"stored": True, "id": row["id"], "updated_at": row["updated_at"]}

        try:
            return run_with_repos(_write)
        except Exception as exc:
            logger.exception(
                "ratecon analysis persist failed shipments_row_id=%s",
                row_shipment_id,
            )
            return {"stored": False, "id": None, "error": str(exc)}
