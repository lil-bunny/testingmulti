import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.services.s3bucket_service import bucket, normalize_object_key
from app.services.attachment_normalizer import _sanitize_path_segment
from app.services.pod_lifecycle.extraction import extract_from_pdf_path as extract_pod_from_pdf_path
from app.services.pod_lifecycle.extraction import pod_confidence_score
from app.tools.pdf_raster import (
    PdfTooLargeError,
    PodPdfTooLargeError,
    freightx_stage_dir,
    make_temp_pdf,
)
from app.services.pod_lifecycle.vs_ratecon_validation import (
    generate_validation_summary,
    validate_pod_against_ratecon,
)
from app.services.ratecon_extraction import extract_from_pdf_path as extract_ratecon_from_pdf_path
from app.models.document import DocumentType
from app.tools.document_analysis import read_ratecon_extraction
from app.tools.documents import read_document, resolve_merged_pod_object_key, resolve_pod_object_key
from app.workflows.shipment_resolver import (
    resolve_shipment_id,
    resolve_shipments_row_id_for_db,
)

logger = logging.getLogger(__name__)


def load_ratecon_analysis(data: dict) -> dict:
    """
    Hydrate ``ratecon_analysis_results`` from cached ``document_analysis`` row
    written by the ratecon workflow (no S3 download or LLM re-run).
    """
    sid = resolve_shipment_id(data)
    if not sid:
        return {"success": False, "error": "missing_shipment_id"}

    shipments_row_id = resolve_shipments_row_id_for_db(data)
    if not shipments_row_id:
        return {"success": False, "error": "missing_shipments_row_id", "shipment_id": sid}

    read_result = read_ratecon_extraction(shipments_row_id)
    if read_result.get("error"):
        return {
            "success": False,
            "error": read_result["error"],
            "shipment_id": sid,
        }
    if not read_result.get("found"):
        logger.info(
            "load_ratecon_analysis: no cached ratecon_extraction shipment_id=%s",
            sid,
        )
        return {
            "success": False,
            "skipped": True,
            "reason": "no_ratecon_extraction",
            "shipment_id": sid,
        }

    row = read_result["row"]
    findings = row.get("results") if isinstance(row.get("results"), dict) else {}
    extracted = findings.get("extracted_fields") if isinstance(findings, dict) else {}
    if not isinstance(extracted, dict):
        extracted = {}

    if not extracted:
        logger.info(
            "load_ratecon_analysis: incomplete cache shipment_id=%s (no extracted_fields)",
            sid,
        )
        return {
            "success": False,
            "skipped": True,
            "reason": "no_ratecon_extraction",
            "shipment_id": sid,
        }

    analysis_id = row.get("id")
    logger.info(
        "load_ratecon_analysis: cache hit shipment_id=%s document_analysis_id=%s",
        sid,
        analysis_id,
    )
    return {
        "success": True,
        "shipment_id": sid,
        "findings": findings,
        "confidence_score": row.get("confidence_score"),
        "document_id": str(row["document_id"]) if row.get("document_id") else None,
        "cached": True,
        "document_analysis_id": str(analysis_id) if analysis_id is not None else None,
    }


def ratecon_analysis(data: dict) -> dict:
    """
    Load the rate confirmation PDF from ``documents`` (``type='ratecon'``) by
    ``shipment_id`` using the stored S3 object key, then run per-page vision extraction.
    Expected object basename: ``ratecon_{shipmentId}.pdf`` (sanitized segment).
    """
    sid = resolve_shipment_id(data)
    if not sid:
        return {"success": False, "error": "missing_shipment_id"}

    shipments_row_id = resolve_shipments_row_id_for_db(data)
    if not shipments_row_id:
        return {"success": False, "error": "missing_shipments_row_id", "shipment_id": sid}

    doc = read_document(shipments_row_id, DocumentType.RATECON)
    if doc.get("error"):
        return {
            "success": False,
            "error": doc["error"],
            "shipment_id": sid,
        }

    if not doc.get("found") or not doc.get("storage_key"):
        logger.info(
            "ratecon_analysis: no ratecon document row for shipment_id=%s",
            sid,
        )
        return {
            "success": True,
            "skipped": True,
            "reason": "no_ratecon_document_in_db",
            "shipment_id": sid,
        }

    raw_key = doc["storage_key"]
    try:
        object_key = normalize_object_key(raw_key)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "shipment_id": sid,
            "ratecon_object_key": raw_key,
        }
    document_id = doc.get("id")
    expected_key = f"ratecon_{_sanitize_path_segment(sid)}.pdf"
    if expected_key.lower() not in (object_key or "").lower():
        logger.warning(
            "ratecon_analysis: object key missing expected basename %r (shipment_id=%s)",
            expected_key,
            sid,
        )
    tmp_path: str | None = None
    stage_dir = freightx_stage_dir(
        settings.RATECON_STAGE_ROOT,
        f"ratecon_{_sanitize_path_segment(sid)}",
    )
    try:
        dl = bucket.download_object_bytes(object_key)
        if not dl.get("success"):
            return {
                "success": False,
                "error": dl.get("error_message") or "s3_download_failed",
                "shipment_id": sid,
                "ratecon_object_key": object_key,
            }
        body = dl["body"]
        if not body.startswith(b"%PDF"):
            return {
                "success": False,
                "error": "downloaded_file_not_pdf",
                "shipment_id": sid,
                "ratecon_object_key": object_key,
            }

        fd, tmp_path = make_temp_pdf(
            prefix=f"ratecon_{sid}",
            directory=stage_dir,
        )
        try:
            os.write(fd, body)
        finally:
            os.close(fd)

        page_results, extracted = extract_ratecon_from_pdf_path(
            tmp_path,
            model_label=settings.LLM_MODEL or "",
            tenant_settings=data.get("tenant_settings"),
            stage_dir=stage_dir,
        )
        good_pages = sum(1 for p in page_results if p.get("extracted_data"))
        has_ids = bool(extracted.get("shipment_identifiers")) or bool(
            extracted.get("primary_identifier")
        )
        if not has_ids and good_pages == 0:
            return {
                "success": False,
                "error": "extraction_empty",
                "shipment_id": sid,
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
            "shipment_id": sid,
            "ratecon_object_key": object_key,
            "ratecon_document_id": document_id,
            "primary_identifier": extracted.get("primary_identifier"),
            "identifiers_found": extracted.get("shipment_identifiers"),
            "findings": findings,
            "document_id": document_id,
            "confidence_score": confidence,
        }
    except Exception as exc:
        logger.exception("ratecon_analysis failed shipment_id=%s", sid)
        return {
            "success": False,
            "error": str(exc),
            "shipment_id": sid,
            "ratecon_object_key": object_key,
        }
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _broker_name_from_ratecon_results(data: dict) -> str | None:
    rc = data.get("ratecon_analysis_results") or {}
    if not rc.get("success") or rc.get("skipped"):
        return None
    findings = rc.get("findings") or {}
    extracted = findings.get("extracted_fields") or {}
    b = extracted.get("broker_name")
    if b is None:
        return None
    s = str(b).strip()
    return s or None


def pod_analysis(data: dict) -> dict:
    """
    Run vision extraction on the merged POD PDF.

    Prefer worker-local staged vision images when all pages are images; else
    ``pod_merged_local_path``; otherwise download from S3. Never expects PDF bytes
    in graph state.
    """
    sid = resolve_shipment_id(data)
    if not sid:
        return {"success": False, "error": "missing_shipment_id"}

    storage_ref, url_meta = resolve_merged_pod_object_key(data)
    if not storage_ref:
        logger.info(
            "pod_analysis: no POD object key in state or documents shipment_id=%s", sid
        )
        return {
            "success": True,
            "skipped": True,
            "reason": "no_pod_object_key",
            "shipment_id": sid,
        }

    try:
        object_key = normalize_object_key(storage_ref)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "shipment_id": sid,
            "pod_object_key": storage_ref,
        }

    merged_doc = data.get("documents_pod") or {}
    document_id: str | None = None
    if url_meta.get("source") == "state":
        document_id = merged_doc.get("id")
    else:
        document_id = url_meta.get("document_id")

    broker_name = _broker_name_from_ratecon_results(data)

    tmp_path: str | None = None
    owned_tmp = False
    try:
        local_path = str(data.get("pod_merged_local_path") or "").strip()
        source = "s3"
        byte_len = 0

        vision_raw = [
            str(p).strip()
            for p in (data.get("pod_vision_image_paths") or [])
            if str(p).strip()
        ]
        merge_raw = [
            str(p).strip()
            for p in (data.get("pod_merge_source_paths") or [])
            if str(p).strip()
        ]
        vision_ok = bool(vision_raw) and all(os.path.isfile(p) for p in vision_raw)
        # Reuse staged images only when every accepted source was an image.
        use_staged_vision = (
            vision_ok
            and bool(merge_raw)
            and len(vision_raw) == len(merge_raw)
            and all(os.path.isfile(p) for p in merge_raw)
        )

        if local_path and os.path.isfile(local_path):
            tmp_path = local_path
            owned_tmp = False
            source = "local_vision_stage" if use_staged_vision else "local_stage"
            try:
                byte_len = os.path.getsize(local_path)
            except OSError:
                byte_len = 0
        else:
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

        page_results, final_pod_data, validation_issues, reconciliation_log = (
            extract_pod_from_pdf_path(
                tmp_path,
                broker_name=broker_name,
                model_label=settings.LLM_MODEL or "",
                tenant_settings=data.get("tenant_settings"),
                prepared_image_paths=vision_raw if use_staged_vision else None,
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
                "page_results": page_results,
                "pod_data": final_pod_data,
            }

        findings = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "pages_processed": len(page_results),
                "successful_pages": ok_pages,
                "failed_pages": len(page_results) - ok_pages,
                "model": settings.LLM_MODEL,
                "pod_object_key_source": url_meta.get("source"),
                "pod_bytes_source": source,
            },
            "pod_data": final_pod_data,
            "validation_issues": validation_issues,
            "reconciliation_log": reconciliation_log,
            "page_details": page_results,
        }
        confidence = pod_confidence_score(page_results, final_pod_data, validation_issues)

        if final_pod_data.get("delivery_confirmed") and not validation_issues:
            pod_status = "PASS"
        elif ok_pages:
            pod_status = "UNKNOWN"
        else:
            pod_status = "FAIL"

        return {
            "success": True,
            "shipment_id": sid,
            "pod_object_key": object_key,
            "pod_document_id": document_id,
            "findings": findings,
            "document_id": document_id,
            "confidence_score": confidence,
            "pod_status": pod_status,
            "delivery_confirmed": final_pod_data.get("delivery_confirmed"),
        }
    except (PdfTooLargeError, PodPdfTooLargeError) as exc:
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

def pod_vs_ratecon_analysis(data: dict) -> dict[str, Any]:
    """
    Compare reconciled POD ``pod_data`` to ratecon ``extracted_fields`` using legacy rules,
    then LLM summary + confidence (same contracts as upstream analysis nodes).

    ponytail: inputs assumed valid — graph error edges and ``ratecon_cache_router`` guarantee
    upstream nodes succeeded before this tool runs; fix upstream, do not re-add guards here.
    """
    sid = resolve_shipment_id(data) or ""
    pod_res = data.get("pod_analysis_results") or {}
    rc_res = data.get("ratecon_analysis_results") or {}
    pod_data = (pod_res.get("findings") or {}).get("pod_data")
    ratecon_data = (rc_res.get("findings") or {}).get("extracted_fields") or {}

    try:
        cross = validate_pod_against_ratecon(
            pod_data,
            ratecon_data,
            tenant_settings=data.get("tenant_settings"),
        )
        summary_result = generate_validation_summary(
            cross,
            pod_data,
            tenant_settings=data.get("tenant_settings"),
        )
    except Exception as exc:
        logger.exception("pod_vs_ratecon_analysis failed shipment_id=%s", sid)
        return {
            "success": False,
            "error": str(exc),
            "shipment_id": sid,
        }

    overall = cross.get("overall_status", "UNKNOWN")
    pod_status = overall if overall in ("PASS", "FAIL") else "UNKNOWN"

    findings: dict[str, Any] = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "model": settings.LLM_MODEL,
        },
        "overall_status": overall,
        "cross_validation": cross,
        "validation_summary": summary_result.get("summary"),
    }

    document_id = pod_res.get("document_id")
    if document_id is not None:
        document_id = str(document_id)

    confidence = summary_result.get("confidence_score")
    if confidence is None:
        confidence = 0.5

    return {
        "success": True,
        "shipment_id": sid,
        "pod_status": pod_status,
        "overall_status": overall,
        "confidence_score": confidence,
        "validation_summary": summary_result.get("summary"),
        "findings": findings,
        "document_id": document_id,
    }