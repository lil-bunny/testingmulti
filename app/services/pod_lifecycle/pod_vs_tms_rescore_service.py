"""Batch POD-vs-TMS rescore: reuse or re-extract from stored S3 POD, then upsert analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.config import settings
from app.core.db import db_scope
from app.core.logger import get_logger
from app.domain.tenant_settings.registry import tenant_settings_for_workflow_state
from app.integrations.turvo.pod_inputs import extract_pod_inputs_from_shipment
from app.models.document_analysis import DocumentAnalysisType
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.pod_lifecycle.extraction import derive_pod_scoring_observations
from app.services.pod_lifecycle.pod_scoring import score_pod
from app.services.pod_lifecycle.stop_matching import build_stop_aware_observations
from app.services.pod_lifecycle.tms_upload_service import (
    PodDocumentNotFoundError,
    PodTmsUploadService,
)
from app.services.shipments_service import ShipmentsService
from app.services.tenants_service import TenantsService
from app.services.worker_queue_routing import apply_async_on_work_queue
from app.tools.document_analysis import upsert_document_analysis
from app.tools.pod import pod_analysis as run_pod_analysis
from app.tools.turvo import get_shipment as get_turvo_shipment

logger = get_logger(__name__)

MAX_BATCH_SIZE = 50

EnqueueStatus = Literal[
    "queued",
    "not_found",
    "no_pod_document",
    "invalid_shipment_id",
    "enqueue_failed",
]
ExtractionSource = Literal["existing", "reanalyzed"]


@dataclass(frozen=True)
class PodVsTmsRescoreEnqueueItem:
    shipment_id: str
    status: EnqueueStatus
    celery_task_id: str | None = None
    shipment_number: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PodVsTmsRescoreProcessResult:
    shipment_id: str
    success: bool
    extraction_source: ExtractionSource | None = None
    document_analysis_id: str | None = None
    final_score: int | None = None
    needs_action: bool | None = None
    error: str | None = None


def _strip_none_values(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none_values(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none_values(item) for item in obj]
    return obj


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _pages_from_extraction_results(results: Any) -> list[dict[str, Any]]:
    if not isinstance(results, dict):
        return []
    pages = results.get("page_evidence")
    if not isinstance(pages, list):
        return []
    return [p for p in pages if isinstance(p, dict)]


class PodVsTmsRescoreService:
    """Enqueue and process POD-vs-TMS rescoring against stored S3 POD documents."""

    def __init__(
        self,
        *,
        shipments_service: ShipmentsService | None = None,
        staging_service: PodTmsUploadService | None = None,
        tenants_service: TenantsService | None = None,
    ) -> None:
        self._shipments = shipments_service or ShipmentsService()
        self._staging = staging_service or PodTmsUploadService()
        self._tenants = tenants_service or TenantsService()

    def enqueue_batch(
        self,
        *,
        tenant_slug: str,
        shipment_ids: list[str],
        use_existing_extraction: bool = True,
    ) -> list[PodVsTmsRescoreEnqueueItem]:
        """Validate each shipment and publish one Celery job on the tenant work queue."""
        slug = _clean(tenant_slug)
        if not slug:
            raise ValueError("tenant_slug is required")

        tenant_uuid = resolve_graph_tenant_to_uuid(slug)
        if not tenant_uuid:
            raise ValueError("unknown tenant")

        cleaned_ids = [_clean(sid) for sid in shipment_ids]
        cleaned_ids = [sid for sid in cleaned_ids if sid]
        if not cleaned_ids:
            raise ValueError("shipment_ids must contain at least one id")
        if len(cleaned_ids) > MAX_BATCH_SIZE:
            raise ValueError(f"shipment_ids exceeds max batch size of {MAX_BATCH_SIZE}")

        from app.tasks.pod_vs_tms_rescore import process_pod_vs_tms_rescore

        items: list[PodVsTmsRescoreEnqueueItem] = []
        for shipment_id in cleaned_ids:
            items.append(
                self._enqueue_one(
                    tenant_slug=slug,
                    tenant_uuid=tenant_uuid,
                    shipment_id=shipment_id,
                    use_existing_extraction=use_existing_extraction,
                    task=process_pod_vs_tms_rescore,
                )
            )
        return items

    def _enqueue_one(
        self,
        *,
        tenant_slug: str,
        tenant_uuid: str,
        shipment_id: str,
        use_existing_extraction: bool,
        task: Any,
    ) -> PodVsTmsRescoreEnqueueItem:
        ship_row = self._shipments.get_by_id(
            tenant_id=tenant_uuid,
            shipment_id=shipment_id,
        )
        if not ship_row:
            return PodVsTmsRescoreEnqueueItem(
                shipment_id=shipment_id,
                status="not_found",
                error="shipment not found",
            )

        row_id = _clean(ship_row.get("id")) or shipment_id
        shipment_number = _clean(ship_row.get("shipment_number"))
        if not shipment_number:
            return PodVsTmsRescoreEnqueueItem(
                shipment_id=row_id,
                status="not_found",
                error="shipment not found",
            )

        try:
            self._staging.resolve_stored_pod_document(shipments_row_id=row_id)
        except PodDocumentNotFoundError as exc:
            return PodVsTmsRescoreEnqueueItem(
                shipment_id=row_id,
                status="no_pod_document",
                shipment_number=shipment_number,
                error=str(exc) or "No POD document on file for shipment",
            )
        except ValueError as exc:
            return PodVsTmsRescoreEnqueueItem(
                shipment_id=row_id,
                status="invalid_shipment_id",
                shipment_number=shipment_number,
                error=str(exc),
            )

        try:
            async_result = apply_async_on_work_queue(
                task,
                tenant_slug=tenant_slug,
                kwargs={
                    "tenant_slug": tenant_slug,
                    "shipment_id": row_id,
                    "use_existing_extraction": use_existing_extraction,
                },
            )
        except Exception as exc:
            logger.exception(
                "pod_vs_tms_rescore enqueue failed shipment_id=%s tenant_slug=%s",
                row_id,
                tenant_slug,
            )
            return PodVsTmsRescoreEnqueueItem(
                shipment_id=row_id,
                status="enqueue_failed",
                shipment_number=shipment_number,
                error=str(exc),
            )

        celery_task_id = str(getattr(async_result, "id", None) or "") or None
        logger.info(
            "pod_vs_tms_rescore queued shipment_id=%s shipment_number=%s "
            "celery_task_id=%s tenant_slug=%s use_existing_extraction=%s",
            row_id,
            shipment_number,
            celery_task_id,
            tenant_slug,
            use_existing_extraction,
        )
        return PodVsTmsRescoreEnqueueItem(
            shipment_id=row_id,
            status="queued",
            celery_task_id=celery_task_id,
            shipment_number=shipment_number,
        )

    def process_one(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        use_existing_extraction: bool = True,
    ) -> PodVsTmsRescoreProcessResult:
        """Load/reuse extraction, re-fetch Turvo, score, upsert ``pod_vs_tms_analysis``."""
        slug = _clean(tenant_slug)
        ship_uuid = _clean(shipment_id)
        if not slug or not ship_uuid:
            return PodVsTmsRescoreProcessResult(
                shipment_id=ship_uuid or "",
                success=False,
                error="missing_tenant_or_shipment_id",
            )

        tenant_uuid = resolve_graph_tenant_to_uuid(slug)
        if not tenant_uuid:
            return PodVsTmsRescoreProcessResult(
                shipment_id=ship_uuid,
                success=False,
                error="unknown_tenant",
            )

        ship_row = self._shipments.get_by_id(
            tenant_id=tenant_uuid,
            shipment_id=ship_uuid,
        )
        if not ship_row:
            return PodVsTmsRescoreProcessResult(
                shipment_id=ship_uuid,
                success=False,
                error="shipment_not_found",
            )

        row_id = _clean(ship_row.get("id")) or ship_uuid
        shipment_number = _clean(ship_row.get("shipment_number"))
        if not shipment_number:
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                error="shipment_not_found",
            )

        try:
            stored_pod = self._staging.resolve_stored_pod_document(
                shipments_row_id=row_id,
            )
        except PodDocumentNotFoundError:
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                error="no_pod_document",
            )

        turvo_shipment = get_turvo_shipment(
            shipment_number,
            tenant_slug=slug,
        )
        if not isinstance(turvo_shipment, dict) or turvo_shipment.get("error"):
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                error="turvo_fetch_failed",
            )
        if not isinstance(turvo_shipment.get("details"), dict):
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                error="turvo_fetch_failed",
            )

        pages, document_id, extraction_source, extract_error = (
            self._resolve_pages(
                tenant_slug=slug,
                tenant_uuid=tenant_uuid,
                shipments_row_id=row_id,
                shipment_number=shipment_number,
                stored_pod=stored_pod,
                turvo_shipment=turvo_shipment,
                use_existing_extraction=use_existing_extraction,
            )
        )
        if extract_error:
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                extraction_source=extraction_source,
                error=extract_error,
            )
        if not pages:
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                extraction_source=extraction_source,
                error="extraction_empty",
            )

        pod_inputs = extract_pod_inputs_from_shipment(turvo_shipment)
        pod_observations = derive_pod_scoring_observations(pages)
        stop_observations = build_stop_aware_observations(pages, pod_inputs)
        pod_observations = {**pod_observations, **stop_observations}

        score = score_pod(pod_observations, pod_inputs)
        score_dict = _strip_none_values(asdict(score))
        persist = upsert_document_analysis(
            row_id,
            DocumentAnalysisType.POD_VS_TMS_ANALYSIS,
            results=score_dict,
            confidence_score=score.final_score / 100,
            document_id=document_id,
        )
        if not persist.get("stored"):
            return PodVsTmsRescoreProcessResult(
                shipment_id=row_id,
                success=False,
                extraction_source=extraction_source,
                error=str(persist.get("error") or "upsert_failed"),
            )

        analysis_id = _clean(persist.get("id"))
        logger.info(
            "pod_vs_tms_rescore stored shipment_id=%s analysis_id=%s "
            "final_score=%s source=%s",
            row_id,
            analysis_id,
            score.final_score,
            extraction_source,
        )
        return PodVsTmsRescoreProcessResult(
            shipment_id=row_id,
            success=True,
            extraction_source=extraction_source,
            document_analysis_id=analysis_id,
            final_score=score.final_score,
            needs_action=score.needs_action,
        )

    def _resolve_pages(
        self,
        *,
        tenant_slug: str,
        tenant_uuid: str,
        shipments_row_id: str,
        shipment_number: str,
        stored_pod: Any,
        turvo_shipment: dict[str, Any],
        use_existing_extraction: bool,
    ) -> tuple[
        list[dict[str, Any]],
        str | None,
        ExtractionSource | None,
        str | None,
    ]:
        document_id = _clean(getattr(stored_pod, "document_id", None))

        if use_existing_extraction:
            existing = self._load_pod_extraction(shipments_row_id)
            if existing is not None:
                pages = _pages_from_extraction_results(existing.get("results"))
                if pages:
                    existing_doc = _clean(existing.get("document_id"))
                    return pages, existing_doc or document_id, "existing", None

        return self._reanalyze_from_s3(
            tenant_slug=tenant_slug,
            tenant_uuid=tenant_uuid,
            shipments_row_id=shipments_row_id,
            shipment_number=shipment_number,
            storage_key=str(stored_pod.storage_key),
            document_id=document_id,
            turvo_shipment=turvo_shipment,
        )

    def _load_pod_extraction(self, shipments_row_id: str) -> dict[str, Any] | None:
        with db_scope() as repos:
            return repos.document_analysis.get_by_shipment_and_type(
                shipment_id=shipments_row_id,
                analysis_type=DocumentAnalysisType.POD_EXTRACTION.value,
            )

    def _reanalyze_from_s3(
        self,
        *,
        tenant_slug: str,
        tenant_uuid: str,
        shipments_row_id: str,
        shipment_number: str,
        storage_key: str,
        document_id: str | None,
        turvo_shipment: dict[str, Any],
    ) -> tuple[
        list[dict[str, Any]],
        str | None,
        ExtractionSource | None,
        str | None,
    ]:
        tenant_settings = self._tenant_settings_for_extraction(tenant_slug)
        analysis = run_pod_analysis(
            {
                "shipment_id": shipment_number,
                "shipments_row_id": shipments_row_id,
                "tenant_id": tenant_uuid,
                "tenant_slug": tenant_slug,
                "tenant_settings": tenant_settings,
                "pod_merged_pdf_object_key": storage_key,
                "documents_pod": {"id": document_id} if document_id else {},
                "shipment": turvo_shipment,
            }
        )
        if not analysis.get("success") or analysis.get("skipped"):
            err = str(analysis.get("error") or analysis.get("reason") or "extraction_failed")
            return [], document_id, "reanalyzed", err

        findings = analysis.get("findings")
        findings = findings if isinstance(findings, dict) else {}
        pages_raw = findings.get("pages")
        pages = [p for p in pages_raw if isinstance(p, dict)] if isinstance(pages_raw, list) else []
        if not pages:
            return [], document_id, "reanalyzed", "extraction_empty"

        analysis_doc_id = _clean(analysis.get("document_id")) or document_id
        persist = upsert_document_analysis(
            shipments_row_id,
            DocumentAnalysisType.POD_EXTRACTION,
            results={"page_evidence": pages},
            confidence_score=analysis.get("confidence_score"),
            llm_model={"model": settings.LLM_PDF_MODEL},
            document_id=analysis_doc_id,
        )
        if not persist.get("stored"):
            logger.warning(
                "pod_vs_tms_rescore: pod_extraction upsert failed shipment_id=%s error=%s",
                shipments_row_id,
                persist.get("error"),
            )
        return pages, analysis_doc_id, "reanalyzed", None

    def _tenant_settings_for_extraction(self, tenant_slug: str) -> dict[str, Any] | None:
        row = self._tenants.get_by_slug(tenant_slug)
        if not row:
            return None
        raw = row.get("settings") if isinstance(row.get("settings"), dict) else {}
        try:
            return tenant_settings_for_workflow_state(tenant_slug, raw)
        except Exception:
            logger.warning(
                "pod_vs_tms_rescore: tenant_settings projection failed slug=%s; "
                "continuing without projected settings",
                tenant_slug,
            )
            return raw or None
