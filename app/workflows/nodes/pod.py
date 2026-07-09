import logging
import shutil
from pathlib import Path

from app.core.config import settings
from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.exceptions import WorkflowException
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.tools.document_analysis import upsert_document_analysis
from app.tools.documents import insert_document
from app.tools.pod import (
    load_ratecon_analysis as load_ratecon_analysis_tool,
    pod_analysis as get_pod_analysis,
    pod_vs_ratecon_analysis as get_pod_vs_ratecon_analysis,
)
from app.services.pod_lifecycle.attachment_normalize_service import (
    PodAttachmentNormalizeService,
    attachment_bytes_by_id_from_state,
)
from app.services.ratecon_document_service import RateconDocumentService
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipments_row_id_for_db
from app.workflows.utils.decorators import safe_node

logger = logging.getLogger(__name__)

_PDF_FETCH_ERRORS = {
    "missing_shipment_id": SystemError.MISSING_SHIPMENT_ID,
    "missing_shipments_row_id": SystemError.MISSING_SHIPMENT_ID,
    "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
}

_POD_ANALYSIS_ERRORS = {
    "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
    "extraction_empty": BusinessError.POD_EXTRACTION_EMPTY,
    "downloaded_file_not_pdf": BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
}

def _raise_on_tool_failure(out: dict, error_map: dict) -> None:
    if out.get("skipped") or out.get("success"):
        return
    key = str(out.get("error") or "").strip()
    raise WorkflowException(error_map.get(key, SystemError.UNEXPECTED_NODE_FAILURE))


def _collect_source_object_keys(state) -> list[str]:
    keys: list[str] = []
    for raw in state.data.get("pod_source_object_keys") or []:
        if raw and str(raw).strip():
            keys.append(str(raw).strip())
    if keys:
        return keys

    merged = state.data.get("pod_merged_pdf_object_key")
    if merged and str(merged).strip():
        return [str(merged).strip()]

    for item in state.data.get("get_email_attachments_results") or []:
        if not isinstance(item, dict) or not item.get("success"):
            continue
        key = item.get("object_key")
        if key and str(key).strip():
            keys.append(str(key).strip())
    return keys


def _cleanup_pod_attachment_stage(state) -> None:
    """Remove worker-local stage dir; only paths live in state, never PDF bytes."""
    state.data.pop("attachment_bytes_by_id", None)
    state.data.pop("get_email_attachments_results", None)
    state.data.pop("pod_attachment_stage_files", None)
    state.data.pop("pod_merged_local_path", None)
    stage_dir = str(state.data.pop("pod_attachment_stage_dir", "") or "").strip()
    if not stage_dir:
        return
    try:
        shutil.rmtree(Path(stage_dir), ignore_errors=True)
    except Exception:
        logger.warning(
            "pod_stage_cleanup_failed shipment_id=%s dir=%s",
            resolve_shipment_id(state.data),
            stage_dir,
        )


@safe_node
def classify_attachments(state):
    """Classify attachments, upload merged PDF, persist ``documents`` row."""
    state.data["pod_source_object_keys"] = list(state.data.get("pod_object_keys") or [])

    result = PodAttachmentNormalizeService().normalize_from_state_data(state.data)
    state.data["attachment_normalization"] = result

    merged = result.get("pod_merged_pdf_object_key")
    local_merged = str(result.get("pod_merged_local_path") or "").strip()
    if result.get("success") and merged:
        state.data["pod_object_keys"] = [merged]
        state.data["pod_merged_pdf_object_key"] = merged
        state.data["has_attachments"] = True
        if local_merged:
            # Path only — never store merged PDF bytes in graph state/checkpoints.
            state.data["pod_merged_local_path"] = local_merged
    else:
        state.data["pod_object_keys"] = []
        state.data.pop("pod_merged_pdf_object_key", None)
        state.data.pop("pod_merged_local_path", None)
        state.data["has_attachments"] = False

    input_count = len(attachment_bytes_by_id_from_state(state.data)) or len(
        state.data.get("pod_source_object_keys") or []
    )
    logger.info(
        "classify_attachments: shipment_id=%s input_attachments=%s success=%s merged=%s rejected=%s",
        resolve_shipment_id(state.data),
        input_count,
        result.get("success"),
        bool(merged),
        len(result.get("rejected") or []),
    )

    norm = state.data.get("attachment_normalization") or {}
    try:
        if not norm.get("success"):
            raise WorkflowException(BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)

        merged_key = state.data.get("pod_merged_pdf_object_key")
        if merged_key:
            source_keys = _collect_source_object_keys(state)
            persist = insert_document(
                DocumentType.POD,
                storage_key=merged_key,
                shipments_row_id=resolve_shipments_row_id_for_db(state.data),
                metadata={"source_object_keys": source_keys},
            )
            state.data["documents_pod"] = persist
            logger.info(
                "classify_attachments: documents pod stored=%s id=%s source_keys=%s",
                persist.get("stored"),
                persist.get("id"),
                len(source_keys),
            )
    finally:
        # Drop raw attachment payloads from state; keep stage_dir + merged local path
        # until pod_analysis so LLM can reuse the local merged PDF without S3 re-download.
        state.data.pop("attachment_bytes_by_id", None)
        state.data.pop("get_email_attachments_results", None)
        state.data.pop("pod_attachment_stage_files", None)
        if not state.data.get("pod_merged_local_path"):
            _cleanup_pod_attachment_stage(state)
    return state


@safe_node
def load_ratecon_analysis(state):
    """
    Load cached ratecon extraction from ``document_analysis`` (ratecon workflow).

    Intentional skips (ratecon not yet processed) fall through silently so
    ``ratecon_cache_router`` can route to ``end`` as usual.
    Hard failures (missing shipment id, S3 error) raise WorkflowException.
    """
    if not state.data.get("shipment_id"):
        resolved = resolve_shipment_id(state.data)
        if resolved:
            state.data["shipment_id"] = resolved

    out = load_ratecon_analysis_tool(state.data)
    state.data["ratecon_analysis_results"] = out

    _raise_on_tool_failure(out, _PDF_FETCH_ERRORS)

    analysis_id = out.get("document_analysis_id")
    if out.get("success") and not out.get("skipped") and analysis_id:
        state.data["document_analysis_ratecon"] = {
            "stored": True,
            "id": analysis_id,
            "source": "cache",
        }
        logger.info(
            "load_ratecon_analysis: cache hit shipment_id=%s id=%s",
            out.get("shipment_id"),
            analysis_id,
        )
    else:
        logger.warning(
            "load_ratecon_analysis: cache miss shipment_id=%s reason=%s",
            out.get("shipment_id"),
            out.get("reason") or out.get("error"),
        )
    return state


def ratecon_analysis(state):
    state.data.update(RateconDocumentService().analyze_and_persist(state.data))
    return state


def _is_manual_pod_upload(data: dict) -> bool:
    return str(data.get("event_type") or "").strip() == (
        WorkflowRunEventType.MANUAL_POD_UPLOAD.value
    )


def _manual_pod_analysis_soft_fail(out: dict) -> bool:
    if out.get("skipped"):
        return True
    if not out.get("success"):
        return str(out.get("error") or "").strip() == "extraction_empty"
    return not (out.get("findings") or {}).get("pod_data")


@safe_node
def pod_analysis(state):
    try:
        out = get_pod_analysis(state.data)
        state.data["pod_analysis_results"] = out

        if _is_manual_pod_upload(state.data) and _manual_pod_analysis_soft_fail(out):
            logger.warning(
                "pod_analysis: manual soft-fail shipment_id=%s lifecycle_id=%s error=%s skipped=%s",
                state.data.get("shipment_id"),
                state.data.get("workflow_lifecycle_id"),
                out.get("error"),
                out.get("skipped"),
            )
            return state

        _raise_on_tool_failure(out, _POD_ANALYSIS_ERRORS)

        if out.get("skipped"):
            raise WorkflowException(BusinessError.POD_EXTRACTION_EMPTY)

        if out.get("success") and not (out.get("findings") or {}).get("pod_data"):
            raise WorkflowException(BusinessError.POD_EXTRACTION_EMPTY)

        shipments_row_id = resolve_shipments_row_id_for_db(state.data)
        if (
            out.get("success")
            and not out.get("skipped")
            and out.get("findings")
            and shipments_row_id
        ):
            persist = upsert_document_analysis(
                shipments_row_id,
                DocumentAnalysisType.POD_EXTRACTION,
                results=out["findings"],
                confidence_score=out.get("confidence_score"),
                llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
                document_id=out.get("document_id"),
            )
            state.data["document_analysis_pod"] = persist
            logger.info(
                "pod_analysis: document_analysis stored=%s id=%s",
                persist.get("stored"),
                persist.get("id"),
            )
        return state
    finally:
        _cleanup_pod_attachment_stage(state)


@safe_node
def pod_vs_ratecon_analysis(state):
    out = get_pod_vs_ratecon_analysis(state.data)
    state.data["pod_vs_ratecon_analysis_results"] = out

    if not out.get("skipped") and not out.get("success"):
        if _is_manual_pod_upload(state.data):
            logger.warning(
                "pod_vs_ratecon_analysis: manual soft-fail shipment_id=%s lifecycle_id=%s error=%s",
                state.data.get("shipment_id"),
                state.data.get("workflow_lifecycle_id"),
                out.get("error"),
            )
            return state
        raise WorkflowException(SystemError.UNEXPECTED_NODE_FAILURE)

    shipments_row_id = resolve_shipments_row_id_for_db(state.data)
    if (
        out.get("success")
        and not out.get("skipped")
        and out.get("findings")
        and shipments_row_id
    ):
        persist = upsert_document_analysis(
            shipments_row_id,
            DocumentAnalysisType.POD_VS_RATECON_COMPARISON,
            results=out["findings"],
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
            document_id=out.get("document_id"),
        )
        state.data["document_analysis_pod_vs_ratecon"] = persist
        logger.info(
            "pod_vs_ratecon_analysis: document_analysis stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    return state
