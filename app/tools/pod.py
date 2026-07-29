import logging
import os
import tempfile
from datetime import datetime

from app.core.config import settings
from app.services.s3bucket_service import bucket, normalize_object_key
from app.services.attachment_normalizer import _sanitize_path_segment
from app.services.pod_lifecycle.extraction import extract_from_pdf_path as extract_pod_from_pdf_path
from app.services.pod_lifecycle.extraction import derive_pod_scoring_observations
from app.integrations.turvo.shipments import carrier_from_order, first_active_carrier_order
from app.tools.pdf_to_images import PdfTooLargeError, make_temp_pdf
from app.tools.documents import resolve_merged_pod_object_key
from app.workflows.shipment_resolver import resolve_shipment_id

logger = logging.getLogger(__name__)


def _carrier_name_from_shipment(data: dict) -> str | None:
    """Assigned carrier name used to exclude carrier letterhead during extraction."""
    shipment = data.get("shipment")
    if not isinstance(shipment, dict):
        return None
    _carrier_id, carrier_name = carrier_from_order(
        first_active_carrier_order(shipment) or {}
    )
    return carrier_name


def pod_analysis(data: dict) -> dict:
    """
    Run direct-PDF extraction on the merged POD PDF (one whole-document LLM call).

    Prefers ``pod_merged_local_path`` (post-merge, pre-S3). Falls back to S3 via
    ``pod_merged_pdf_object_key`` / ``documents`` when no local file. Never expects
    PDF bytes in graph state.
    """
    sid = resolve_shipment_id(data)
    if not sid:
        return {"success": False, "error": "missing_shipment_id"}

    local_path = str(data.get("pod_merged_local_path") or "").strip()
    has_local = bool(local_path and os.path.isfile(local_path))

    storage_ref, url_meta = resolve_merged_pod_object_key(data)
    object_key: str | None = None
    if storage_ref:
        try:
            object_key = normalize_object_key(storage_ref)
        except ValueError as exc:
            if not has_local:
                return {
                    "success": False,
                    "error": str(exc),
                    "shipment_id": sid,
                    "pod_object_key": storage_ref,
                }
            logger.warning(
                "pod_analysis: ignoring invalid S3 ref; using local path shipment_id=%s",
                sid,
            )
            url_meta = {}

    if not has_local and not object_key:
        logger.info(
            "pod_analysis: no local merged PDF and no S3 key shipment_id=%s", sid
        )
        return {
            "success": True,
            "skipped": True,
            "reason": "no_pod_source",
            "shipment_id": sid,
        }

    merged_doc = data.get("documents_pod") or {}
    document_id: str | None = None
    if url_meta.get("source") == "state":
        document_id = merged_doc.get("id")
    elif url_meta.get("source") == "documents":
        document_id = url_meta.get("document_id")

    broker_name = _carrier_name_from_shipment(data)

    tmp_path: str | None = None
    owned_tmp = False
    try:
        source = "s3"
        byte_len = 0

        if has_local:
            tmp_path = local_path
            owned_tmp = False
            source = "local_stage"
            try:
                byte_len = os.path.getsize(local_path)
            except OSError:
                byte_len = 0
        else:
            assert object_key is not None
            dl = bucket.download_object_bytes(object_key)
            if not dl.get("success"):
                return {
                    "success": False,
                    "error": dl.get("error_message") or "s3_download_failed",
                    "shipment_id": sid,
                    "pod_object_key": object_key,
                }
            body = dl["body"]
            source = "s3"
            byte_len = len(body)
            suffix = ".pdf" if body.startswith(b"%PDF") else ".jpg"
            if suffix == ".pdf":
                fd, tmp_path = make_temp_pdf(prefix=f"pod_{sid}")
            else:
                fd, tmp_path = tempfile.mkstemp(
                    prefix=f"pod_{_sanitize_path_segment(sid)}_",
                    suffix=suffix,
                )
            owned_tmp = True
            try:
                os.write(fd, body)
            finally:
                os.close(fd)

        suffix = ".pdf" if (tmp_path or "").lower().endswith(".pdf") else ".bin"
        logger.info(
            "pod_analysis: extracted temp file shipment_id=%s suffix=%s bytes=%s source=%s",
            sid,
            suffix,
            byte_len,
            source,
        )

        page_results, _, _, _, raw_llm_response = (
            extract_pod_from_pdf_path(
                tmp_path,
                broker_name=broker_name,
                model_label=settings.LLM_PDF_MODEL,
                tenant_settings=data.get("tenant_settings"),
            )
        )

        ok_pages = sum(
            1 for p in page_results if p.get("extracted_data") and not p.get("error")
        )
        if ok_pages == 0:
            return {
                "success": False,
                "error": "extraction_empty",
                "shipment_id": sid,
                "pod_object_key": object_key,
            }

        pages = (raw_llm_response or {}).get("pages")
        pages = pages if isinstance(pages, list) else []
        pod_observations = derive_pod_scoring_observations(pages)

        findings = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "pages_processed": len(page_results),
                "successful_pages": ok_pages,
                "failed_pages": len(page_results) - ok_pages,
                "model": settings.LLM_PDF_MODEL,
                "pod_object_key_source": url_meta.get("source"),
                "pod_bytes_source": source,
            },
            "pages": pages,
            "pod_observations": pod_observations,
        }
        return {
            "success": True,
            "shipment_id": sid,
            "pod_object_key": object_key,
            "pod_document_id": document_id,
            "findings": findings,
            "document_id": document_id,
            "confidence_score": None,
        }
    except PdfTooLargeError as exc:
        logger.warning(
            "pod_analysis: PDF too large to convert shipment_id=%s error=%s",
            sid,
            exc,
        )
        return {
            "success": False,
            "error": PdfTooLargeError.error_key,
            "error_message": str(exc),
            "shipment_id": sid,
            "pod_object_key": object_key,
        }
    except Exception as exc:
        logger.exception("pod_analysis failed shipment_id=%s", sid)
        return {
            "success": False,
            "error": str(exc),
            "shipment_id": sid,
            "pod_object_key": object_key,
        }
    finally:
        if owned_tmp and tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
