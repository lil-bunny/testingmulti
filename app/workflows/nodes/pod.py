import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from app.core.config import settings
from app.domain.activity_log_descriptions import format_pod_only_ratecon_pages_found_info
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.exceptions import WorkflowException
from app.integrations.turvo.pod_inputs import extract_pod_inputs_from_shipment
from app.models.activity_type import ActivityType
from app.models.document_analysis import DocumentAnalysisType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.activity_log_service import ActivityLogService
from app.services.pod_lifecycle.pod_scoring import score_pod
from app.services.pod_lifecycle.ratecon_page_trim import RateconPageTrimService
from app.services.pod_lifecycle.stop_matching import build_stop_aware_observations
from app.tools.document_analysis import upsert_document_analysis
from app.tools.pod import pod_analysis as get_pod_analysis
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipments_row_id_for_db
from app.workflows.utils.decorators import safe_node

logger = logging.getLogger(__name__)

_POD_ANALYSIS_ERRORS = {
    "s3_download_failed": IntegrationError.POD_S3_DOWNLOAD_FAILED,
    "llm_gateway_timeout": IntegrationError.LLM_GATEWAY_TIMEOUT,
    "extraction_empty": BusinessError.POD_EXTRACTION_EMPTY,
    "downloaded_file_not_pdf": BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
    "pdf_too_large": SystemError.PDF_TOO_LARGE,
}


def _raise_on_tool_failure(out: dict, error_map: dict) -> None:
    if out.get("skipped") or out.get("success"):
        return
    key = str(out.get("error") or "").strip()
    raise WorkflowException(error_map.get(key, SystemError.UNEXPECTED_NODE_FAILURE))


def _cleanup_pod_attachment_stage(state) -> None:
    """Remove worker-local stage dir; only paths live in state, never PDF bytes."""
    state.data.pop("pod_merged_local_path", None)
    state.data.pop("pod_trimmed_local_path", None)
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
def merge_pod_attachments_local(state):
    """
    In-graph merge of pre-classified staged POD attachments to a local PDF.

    Classification/staging runs pre-graph; this node only merges local sources.
    S3 upload happens after LLM trim via ``upload_trimmed_pod_attachments``.
    """
    from app.services.pod_lifecycle.attachment_pipeline_service import (
        PodAttachmentPipelineService,
    )

    try:
        pipeline_service = PodAttachmentPipelineService()
        result = pipeline_service.merge_local_from_state(state.data)
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
    return not (out.get("findings") or {}).get("pages")


@safe_node
def pod_analysis(state):
    """
    Extract PoD fields from the merged local PDF and upsert ``pod_extraction``.

    Manual uploads soft-fail on empty extraction; other paths raise via
    ``_POD_ANALYSIS_ERRORS``. Stage cleanup is deferred until after upload / end.
    """
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
        reason = str(out.get("reason") or "").strip()
        # Pre-upload path: no local merged PDF and no S3 key yet / at all.
        if reason in ("no_pod_source", "no_pod_object_key"):
            raise WorkflowException(BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)
        raise WorkflowException(BusinessError.POD_EXTRACTION_EMPTY)

    if out.get("success") and not (out.get("findings") or {}).get("pages"):
        raise WorkflowException(BusinessError.POD_EXTRACTION_EMPTY)

    shipments_row_id = resolve_shipments_row_id_for_db(state.data)
    findings = out.get("findings") if isinstance(out.get("findings"), dict) else {}
    if (
        out.get("success")
        and not out.get("skipped")
        and findings.get("pages")
        and shipments_row_id
    ):
        # Persist the canonical page evidence once; observations stay in state for scoring.
        persist = upsert_document_analysis(
            shipments_row_id,
            DocumentAnalysisType.POD_EXTRACTION,
            results={"page_evidence": findings.get("pages")},
            confidence_score=out.get("confidence_score"),
            llm_model={"model": settings.LLM_PDF_MODEL},
            document_id=out.get("document_id"),
        )
        state.data["pod_analysis_stored"] = persist.get("stored") is True
        analysis_id = str(persist.get("id") or "").strip()
        if analysis_id:
            state.data["pod_analysis_id"] = analysis_id
        logger.info(
            "pod_analysis: document_analysis stored=%s id=%s",
            persist.get("stored"),
            persist.get("id"),
        )
    return state


def _llm_pages_from_state(data: dict) -> object:
    results = data.get("pod_analysis_results")
    results = results if isinstance(results, dict) else {}
    findings = results.get("findings")
    findings = findings if isinstance(findings, dict) else {}
    return findings.get("pages")


def _record_only_ratecon_info(state) -> None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "trim_ratecon_pages_from_pod: ONLY_RATECON info skipped missing ids"
        )
        return
    excluded = state.data.get("pod_ratecon_excluded_pages") or []
    activity_log_service = ActivityLogService()
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.INFO,
                    description=format_pod_only_ratecon_pages_found_info(),
                    metadata={
                        "reason": "ONLY_RATECON_PAGES_FOUND",
                        "excluded_page_numbers": excluded,
                    },
                    update_lifecycle=False,
                ),
            ),
        )
    )


@safe_node
def trim_ratecon_pages_from_pod(state):
    """
    Drop LLM-labeled RATE_CONFIRMATION pages from the local merged PDF.

    Soft-exits with INFO when every page is rate confirmation; hard-fails when
    ``pages[]`` is unusable.
    """
    pages = _llm_pages_from_state(state.data)
    merged_local = str(state.data.get("pod_merged_local_path") or "").strip()
    stage_dir = str(state.data.get("pod_attachment_stage_dir") or "").strip() or None
    shipment_number = str(state.data.get("shipment_id") or "").strip() or None

    ratecon_page_trim_service = RateconPageTrimService()
    result = ratecon_page_trim_service.trim_local_pdf(
        merged_local_path=merged_local,
        pages=pages,
        stage_dir=stage_dir,
        shipment_number=shipment_number,
    )
    if result.error == "pages_unusable":
        raise WorkflowException(BusinessError.POD_PAGE_TYPES_UNUSABLE)
    if result.error:
        raise WorkflowException(BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)

    state.data["pod_ratecon_excluded_pages"] = list(result.excluded_page_numbers)
    if result.outcome == "only_ratecon":
        state.data["pod_trim_outcome"] = "only_ratecon"
        state.data.pop("pod_trimmed_local_path", None)
        _record_only_ratecon_info(state)
        return state

    state.data["pod_trim_outcome"] = "continue"
    if result.trimmed_local_path:
        state.data["pod_trimmed_local_path"] = result.trimmed_local_path
    else:
        state.data.pop("pod_trimmed_local_path", None)
    return state


@safe_node
def upload_trimmed_pod_attachments(state):
    """Upload preferred local POD PDF (trimmed when set) and persist ``documents``."""
    from app.services.pod_lifecycle.attachment_pipeline_service import (
        PodAttachmentPipelineService,
    )

    try:
        pipeline_service = PodAttachmentPipelineService()
        result = pipeline_service.upload_preferred_from_state(state.data)
        if not result.success:
            raise WorkflowException(BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)
        if result.state_patch:
            state.data.update(result.state_patch)
        _cleanup_pod_attachment_stage(state)
        return state
    except WorkflowException:
        _cleanup_pod_attachment_stage(state)
        raise
    except Exception:
        _cleanup_pod_attachment_stage(state)
        raise


def _pod_analysis_findings(state) -> dict:
    pod_results = state.data.get("pod_analysis_results")
    pod_results = pod_results if isinstance(pod_results, dict) else {}
    findings = pod_results.get("findings")
    return findings if isinstance(findings, dict) else {}


def _pod_extraction_persisted(state) -> bool:
    return state.data.get("pod_analysis_stored") is True


@safe_node
def pod_scoring(state):
    """
    Score the PoD against Turvo inputs and persist a ``pod_vs_tms_analysis`` row.

    Uses all Turvo stops and in-memory page evidence; does not overwrite the
    ``pod_extraction`` row.
    """
    shipment = state.data.get("shipment") or {}
    pod_inputs = extract_pod_inputs_from_shipment(shipment)

    findings = _pod_analysis_findings(state)
    pod_observations = findings.get("pod_observations")
    pod_observations = pod_observations if isinstance(pod_observations, dict) else {}
    pages = findings.get("pages")
    stop_observations = build_stop_aware_observations(
        pages,
        pod_inputs,
    )
    if isinstance(pages, list):
        pod_observations = {**pod_observations, **stop_observations}

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
        logger.info(
            "pod_scoring: document_analysis stored=%s id=%s type=%s "
            "final_score=%s needs_action=%s",
            persist.get("stored"),
            persist.get("id"),
            DocumentAnalysisType.POD_VS_TMS_ANALYSIS.value,
            score.final_score,
            score.needs_action,
        )
    return state
