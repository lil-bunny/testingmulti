"""Node: resolve domestic Gelita tenders skipped due to pack code."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.ingest_source_fields import pack_code_for_product_gap
from app.domain.load_tendering_state import get_tender, get_tender_products
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def _matched_skipped_pack_code(state_data: dict[str, Any]) -> str:
    """Resolve skipped pack code from ``read_tender_row`` or tender product lines."""
    matched = str(state_data.get("matched_skipped_pack_code") or "").strip()
    if matched:
        return matched
    skipped = frozenset(state_data.get("skipped_pack_codes") or ())
    if not skipped:
        return ""
    tender = get_tender(state_data) or {}
    for product in get_tender_products(tender):
        pack_code = pack_code_for_product_gap(product)
        if pack_code in skipped:
            return pack_code
    return ""


def resolve_pack_code_skip(state):
    """Log pack-code skip info and mark lifecycle resolved manually."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "resolve_pack_code_skip skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(wl_id),
            bool(tenant_id),
            bool(run_id),
        )
        return state

    pack_code = _matched_skipped_pack_code(state.data)
    metadata: dict[str, Any] = {
        "error": BusinessError.PACK_CODE_SKIPPED.value,
    }
    if pack_code:
        metadata["pack_code"] = pack_code

    description = format_error_message(
        BusinessError.PACK_CODE_SKIPPED,
        pack_code=pack_code,
    )

    activity_log_service = ActivityLogService()
    activity_log_service.record_info(
        ActivityLogWrite(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            description=description,
            metadata=metadata,
            actor_type=ActorType.SYSTEM,
        )
    )

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=StatusType.COMPLETED,
        to_sub_status=StatusSubType.RESOLVED_MANUALLY,
        actor_type=ActorType.SYSTEM,
    )
    return state
