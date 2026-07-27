import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from app.core.config import settings
from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.exceptions import WorkflowException
from app.integrations.turvo.pod_inputs import extract_pod_inputs_from_shipment
from app.models.document_analysis import DocumentAnalysisType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_lifecycle.pod_scoring import score_pod
from app.tools.document_analysis import upsert_document_analysis
from app.tools.pod import pod_analysis as get_pod_analysis
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipments_row_id_for_db
from app.workflows.utils.decorators import safe_node

logger = logging.getLogger(__name__)

_POD_ANALYSIS_ERRORS = {
    "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
    "extraction_empty": BusinessError.POD_EXTRACTION_EMPTY,
    "downloaded_file_not_pdf": BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
    "pdf_too_large": SystemError.PDF_TOO_LARGE,
    # Legacy wire key from earlier POD-only raster guard.
    "pod_pdf_too_large": SystemError.PDF_TOO_LARGE,
}


def _raise_on_tool_failure(out: dict, error_map: dict) -> None:
    if out.get("skipped") or out.get("success"):
        return
    key = str(out.get("error") or "").strip()
    raise WorkflowException(error_map.get(key, SystemError.UNEXPECTED_NODE_FAILURE))


def _cleanup_pod_attachment_stage(state) -> None:
    """Remove worker-local stage dir; only paths live in state, never PDF bytes."""
    state.data.pop("pod_merged_local_path", None)
    state.data.pop("pod_merge_source_paths", None)
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
def merge_and_upload_pod_attachments(state):
    """
    In-graph merge + S3 upload of pre-classified staged POD attachments.

    Classification/staging runs pre-graph; this node only merges local sources,
    uploads the merged PDF, and persists the ``documents`` row.
    """
    from app.services.pod_lifecycle.attachment_pipeline_service import (
        PodAttachmentPipelineService,
    )

    try:
        pipeline_service = PodAttachmentPipelineService()
        result = pipeline_service.merge_and_upload_from_state(state.data)
        if not result.success:
            raise WorkflowException(BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)
        if result.state_patch:
            state.data.update(result.state_patch)
        return state
    except WorkflowException:
        _cleanup_pod_attachment_stage(state)
        raise
    except Exception:
        _cleanup_pod_attachment_stage(state)
        raise


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
    """
    Extract PoD fields from the merged PDF and upsert ``pod_extraction``.

    Manual uploads soft-fail on empty extraction; other paths raise via
    ``_POD_ANALYSIS_ERRORS``. Always cleans the worker stage dir in ``finally``.
    """
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
        findings = out.get("findings") if isinstance(out.get("findings"), dict) else {}
        if (
            out.get("success")
            and not out.get("skipped")
            and findings.get("pod_data")
            and shipments_row_id
        ):
            # Persist extract-only shape; scoring/observations stay in state findings.
            persist = upsert_document_analysis(
                shipments_row_id,
                DocumentAnalysisType.POD_EXTRACTION,
                results={
                    "pod_data": findings.get("pod_data"),
                    "llm_extraction": findings.get("llm_extraction"),
                },
                confidence_score=out.get("confidence_score"),
                llm_model={"model": settings.LLM_PDF_MODEL},
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
def capture_turvo_shipment_snapshot(state):
    """
    Store a dict snapshot of Turvo PoD-scoring inputs on state for audit/debug.

    ``pod_scoring`` re-extracts from ``state.data["shipment"]`` itself (cheap, pure)
    rather than reconstructing dataclasses from this dict.
    """
    shipment = state.data.get("shipment") or {}
    pod_inputs = extract_pod_inputs_from_shipment(shipment)
    state.data["turvo_shipment_snapshot"] = asdict(pod_inputs)
    return state


def _pod_analysis_findings(state) -> dict:
    pod_results = state.data.get("pod_analysis_results")
    pod_results = pod_results if isinstance(pod_results, dict) else {}
    findings = pod_results.get("findings")
    return findings if isinstance(findings, dict) else {}


def _pod_extraction_persisted(state) -> bool:
    persist = state.data.get("document_analysis_pod")
    return isinstance(persist, dict) and persist.get("stored") is True


@safe_node
def pod_scoring(state):
    """
    Score the PoD against Turvo inputs and persist a ``pod_vs_tms_analysis`` row.

    Skips multi-stop shipments. Uses in-memory ``pod_analysis`` findings
    (``pod_observations``); does not overwrite the ``pod_extraction`` row.
    """
    shipment = state.data.get("shipment") or {}
    pod_inputs = extract_pod_inputs_from_shipment(shipment)

    if not pod_inputs.is_single_stop:
        state.data["pod_scoring_results"] = {
            "success": True,
            "skipped": True,
            "reason": "multi_stop_not_supported",
        }
        return state

    findings = _pod_analysis_findings(state)
    pod_observations = findings.get("pod_observations")
    pod_observations = pod_observations if isinstance(pod_observations, dict) else {}

    score = score_pod(pod_observations, pod_inputs)
    score_dict = asdict(score)
    state.data["pod_scoring_results"] = {"success": True, "score": score_dict}

    shipments_row_id = resolve_shipments_row_id_for_db(state.data)
    if shipments_row_id and _pod_extraction_persisted(state):
        pod_results = state.data.get("pod_analysis_results") or {}
        persist = upsert_document_analysis(
            shipments_row_id,
            DocumentAnalysisType.POD_VS_TMS_ANALYSIS,
            results=score_dict,
            confidence_score=score.final_score / 100,
            document_id=pod_results.get("document_id"),
        )
        state.data["document_analysis_pod_scoring"] = persist
        logger.info(
            "pod_scoring: document_analysis stored=%s id=%s type=%s "
            "final_score=%s result=%s",
            persist.get("stored"),
            persist.get("id"),
            DocumentAnalysisType.POD_VS_TMS_ANALYSIS.value,
            score.final_score,
            score.result,
        )
    return state
