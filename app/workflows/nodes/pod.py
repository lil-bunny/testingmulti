import logging

from app.core.config import settings
from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.domain.pod_lifecycle_state import raise_for_pod_tool_failure, shipment_id_from_data
from app.exceptions import WorkflowException
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.tools.document_analysis import upsert_document_analysis, upsert_ratecon_extraction
from app.tools.documents import insert_document
from app.tools.pod import (
    classify_attachments as get_normalized_attachments,
    load_ratecon_analysis as load_ratecon_analysis_tool,
    pod_analysis as get_pod_analysis,
    pod_vs_ratecon_analysis as get_pod_vs_ratecon_analysis,
    ratecon_analysis as get_ratecon_analysis,
)
from app.workflows.shipment_resolver import resolve_shipments_row_id_for_db
from app.workflows.utils.decorators import safe_node

logger = logging.getLogger(__name__)


def _collect_source_object_keys(state) -> list[str]:
    keys: list[str] = []
    for raw in state.data.get("pod_source_object_keys") or []:
        if raw and str(raw).strip():
            keys.append(str(raw).strip())
    if keys:
        return keys

    for item in state.data.get("get_email_attachments_results") or []:
        if not isinstance(item, dict) or not item.get("success"):
            continue
        key = item.get("object_key")
        if key and str(key).strip():
            keys.append(str(key).strip())
    return keys


@safe_node
def classify_attachments(state):
    """Normalize POD attachments and persist one merged ``documents`` row."""

    Ensures state.data['pod_object_keys'] lists S3 object keys for uploaded attachments
    and aligns has_attachments for downstream process_pod.
    Raises WorkflowException(POD_ATTACHMENT_UPLOAD_FAILED) when normalization fails.
    """

    # Processes ``pod_object_keys`` (and optional HTTP(S) refs) and returns ``pod_merged_pdf_object_key`` plus metadata
    state.data["pod_source_object_keys"] = list(state.data.get("pod_object_keys") or [])

    get_normalized_attachments(state)

    norm = state.data.get("attachment_normalization") or {}
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
    return state


@safe_node
def load_ratecon_analysis(state):
    """
    Load cached ratecon extraction from ``document_analysis`` (ratecon workflow).

    Intentional skips (ratecon not yet processed) fall through silently so
    ``ratecon_cache_router`` can route to ``end`` as usual.
    Hard failures (missing shipment id, S3 error) raise WorkflowException.
    """
    # Enrich shipment_id on state before any potential raise so error_handler can log it
    if not state.data.get("shipment_id"):
        resolved = shipment_id_from_data(state.data)
        if resolved:
            state.data["shipment_id"] = resolved

    out = load_ratecon_analysis_tool(state.data)
    state.data["ratecon_analysis_results"] = out

    raise_for_pod_tool_failure(out, {
        "missing_shipment_id": SystemError.MISSING_SHIPMENT_ID,
        "missing_shipments_row_id": SystemError.MISSING_SHIPMENT_ID,
        "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
    })

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
    out = get_ratecon_analysis(state.data)
    state.data["ratecon_analysis_results"] = out
    shipments_row_id = resolve_shipments_row_id_for_db(state.data)
    if (
        out.get("success")
        and not out.get("skipped")
        and out.get("findings")
        and shipments_row_id
    ):
        persist = upsert_ratecon_extraction(
            shipments_row_id,
            results=out["findings"],
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
            document_id=out.get("document_id"),
        )
        state.data["document_analysis_ratecon"] = persist
    return state


@safe_node
def pod_analysis(state):
    out = get_pod_analysis(state.data)
    state.data["pod_analysis_results"] = out

    raise_for_pod_tool_failure(out, {
        "missing_shipment_id": SystemError.MISSING_SHIPMENT_ID,
        "missing_shipments_row_id": SystemError.MISSING_SHIPMENT_ID,
        "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
        "downloaded_file_not_pdf": BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
        "extraction_empty": BusinessError.POD_EXTRACTION_EMPTY,
    })

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


@safe_node
def pod_vs_ratecon_analysis(state):
    out = get_pod_vs_ratecon_analysis(state.data)
    state.data["pod_vs_ratecon_analysis_results"] = out

    raise_for_pod_tool_failure(out, {
        "missing_pod_data": BusinessError.MISSING_POD_DATA,
        "missing_ratecon_data": BusinessError.MISSING_RATECON_DATA,
    })

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
