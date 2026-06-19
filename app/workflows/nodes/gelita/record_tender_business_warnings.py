"""Node: persist ``tender_business_warnings`` as exception activity rows before vendor log."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.tender_business_warnings import (
    filter_primary_business_warnings,
    get_tender_business_warnings,
    warning_context,
)
from app.models.activity_type import ActorType
from app.services.activity_log_service import ActivityLogService

logger = get_logger(__name__)


def record_tender_business_warnings(state):
    """Persist business gaps as exception rows; does not change lifecycle status."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()

    warnings = filter_primary_business_warnings(get_tender_business_warnings(state.data))
    if not warnings:
        return state

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "record_tender_business_warnings skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(wl_id),
            bool(tenant_id),
            bool(run_id),
        )
        return state

    activity_log_service = ActivityLogService()
    for warning in warnings:
        metadata: dict[str, Any] = {}
        code = warning.get("code")
        if code:
            metadata["error"] = code
        if tender_id:
            metadata["tender_id"] = tender_id
        context = warning_context(warning)
        if context.get("pack_code"):
            metadata["pack_code"] = context["pack_code"]
        if context.get("del_code"):
            metadata["delivery_address_code"] = context["del_code"]
        if context.get("tender_product_id"):
            metadata["tender_product_id"] = context["tender_product_id"]
        activity_log_service.record_exception(
            ActivityLogWrite(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                description=warning.get("message"),
                metadata=metadata or None,
                actor_type=ActorType.SYSTEM,
            )
        )
    return state
