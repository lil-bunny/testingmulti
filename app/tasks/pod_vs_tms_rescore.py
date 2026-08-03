"""Celery tasks for POD-vs-TMS rescore (stored S3 POD + optional re-extract)."""

from __future__ import annotations

from app.celery_app import celery_app
from app.core.logger import get_logger
from app.services.pod_lifecycle.pod_vs_tms_rescore_service import PodVsTmsRescoreService

logger = get_logger(__name__)

_TASK_NAME = "app.tasks.pod_vs_tms_rescore.process_pod_vs_tms_rescore"


@celery_app.task(name=_TASK_NAME, ignore_result=True)
def process_pod_vs_tms_rescore(
    *,
    tenant_slug: str,
    shipment_id: str,
    use_existing_extraction: bool = True,
) -> None:
    """Worker entry: rescore one shipment and upsert ``pod_vs_tms_analysis``."""
    logger.info(
        "process_pod_vs_tms_rescore start tenant_slug=%s shipment_id=%s "
        "use_existing_extraction=%s",
        tenant_slug,
        shipment_id,
        use_existing_extraction,
    )
    pod_vs_tms_rescore_service = PodVsTmsRescoreService()
    result = pod_vs_tms_rescore_service.process_one(
        tenant_slug=tenant_slug,
        shipment_id=shipment_id,
        use_existing_extraction=use_existing_extraction,
    )
    if result.success:
        logger.info(
            "process_pod_vs_tms_rescore ok shipment_id=%s analysis_id=%s "
            "final_score=%s source=%s",
            result.shipment_id,
            result.document_analysis_id,
            result.final_score,
            result.extraction_source,
        )
        return
    logger.warning(
        "process_pod_vs_tms_rescore failed shipment_id=%s error=%s source=%s",
        result.shipment_id,
        result.error,
        result.extraction_source,
    )
