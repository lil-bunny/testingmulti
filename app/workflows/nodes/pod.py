import logging

from app.core.config import settings
from app.models.document import DocumentType
from app.tools.documents import insert_document
from app.tools.pod import ratecon_analysis as get_ratecon_analysis, classify_attachments as get_normalized_attachments, pod_analysis as get_pod_analysis, pod_vs_ratecon_analysis as get_pod_vs_ratecon_analysis
from app.models.document_analysis import DocumentAnalysisType
from app.tools.document_analysis import upsert_document_analysis, upsert_ratecon_extraction
from app.workflows.shipment_resolver import resolve_shipment_id

logger = logging.getLogger(__name__)


def _first_source_attachment_id(state) -> str | None:
    for item in state.data.get("get_email_attachments_results") or []:
        aid = item.get("attachment_id")
        if aid and item.get("success"):
            return aid
    attachments = state.data.get("attachments") or []
    if attachments:
        return attachments[0].get("id")
    return None


def classify_attachments(state):
    """
    Normalize POD attachment inputs after get_email_attachments.

    Ensures state.data['pod_object_keys'] lists S3 object keys for uploaded attachments
    and aligns has_attachments for downstream process_pod.
    """

    # 1. Processes ``pod_object_keys`` (and optional HTTP(S) refs) and returns ``pod_merged_pdf_object_key`` plus metadata
    get_normalized_attachments(state)

    merged_key = state.data.get("pod_merged_pdf_object_key")
    shipment_id = resolve_shipment_id(state.data) or None
    # 2. Insert merged POD into documents table
    if merged_key and shipment_id:
        persist = insert_document(
            DocumentType.POD_MERGED_FINAL,
            shipment_id,
            merged_key,
            email_id=state.data.get("email_id"),
            attachment_id=_first_source_attachment_id(state),
        )
        state.data["documents_pod_merged"] = persist
        logger.info(
            "classify_attachments: documents pod_merged stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    elif merged_key and not shipment_id:
        logger.warning(
            "classify_attachments: merged PDF object key present but no shipment_id; skipping documents row"
        )
    return state


def ratecon_analysis(state):
    out = get_ratecon_analysis(state.data)
    state.data["ratecon_analysis_results"] = out
    if (
        out.get("success")
        and not out.get("skipped")
        and out.get("findings")
        and out.get("shipment_id")
    ):
        persist = upsert_ratecon_extraction(
            out["shipment_id"],
            status="completed",
            findings=out["findings"],
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
            attachments_used=out.get("attachments_used"),
        )
        state.data["document_analysis_ratecon"] = persist
        logger.info(
            "ratecon_analysis: document_analysis stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    return state


def pod_analysis(state):
    out = get_pod_analysis(state.data)
    state.data["pod_analysis_results"] = out
    if (
        out.get("success")
        and not out.get("skipped")
        and out.get("findings")
        and out.get("shipment_id")
    ):
        persist = upsert_document_analysis(
            out["shipment_id"],
            DocumentAnalysisType.POD_EXTRACTION,
            status="completed",
            findings=out["findings"],
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
            attachments_used=out.get("attachments_used"),
        )
        state.data["document_analysis_pod"] = persist
        logger.info(
            "pod_analysis: document_analysis stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    return state


def pod_vs_ratecon_analysis(state):
    out = get_pod_vs_ratecon_analysis(state.data)
    state.data["pod_vs_ratecon_analysis_results"] = out
    if (
        out.get("success")
        and not out.get("skipped")
        and out.get("findings")
        and out.get("shipment_id")
    ):
        persist = upsert_document_analysis(
            out["shipment_id"],
            DocumentAnalysisType.POD_VS_RATECON_COMPARISON,
            status="completed",
            findings=out["findings"],
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_MODEL} if settings.LLM_MODEL else None,
            attachments_used=out.get("attachments_used"),
        )
        state.data["document_analysis_pod_vs_ratecon"] = persist
        logger.info(
            "pod_vs_ratecon_analysis: document_analysis stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    return state
