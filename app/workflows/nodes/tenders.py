"""Nodes for Tenders table."""

from app.core.logger import get_logger
from app.domain.error_catalog import BusinessError, SystemError
from app.domain.ingest_source_fields import pack_code_for_product_gap
from app.domain.gelita.routing_guide_lifecycle import (
    mark_stale_routing_guide_reminder_if_needed,
    routing_guide_attempt_from_metadata,
    routing_guide_has_attempt,
    sync_routing_guide_attempt_to_state,
)
from app.domain.load_tendering_settings import (gelita_domestic_delivery_settings, gelita_skipped_pack_codes_settings), is_ftl_load_type, resolve_load_type
from app.domain.load_tendering_state import (get_tender, get_tender_products, set_tender, tender_from_read_order)
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.workflows.utils.decorators import safe_node

logger = get_logger(__name__)


def _delivery_country_from_order(order: dict) -> str | None:
    delivery_address = order.get("delivery_address")
    if not isinstance(delivery_address, dict):
        return None
    country = delivery_address.get("country")
    if country is None:
        return None
    text = str(country).strip()
    return text or None


@safe_node
def read_tender_row(state):
    """Load order + product lines into ``state.data['tender']``."""
    tender_id = str(state.data.get("tender_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    event_type = str(state.data.get("event_type") or "").strip()
    is_tender_created = event_type == "tender_created"
    scheduled_routing_guide_attempt = (
        state.data.get("routing_guide_attempt")
        if event_type in ("reminder_due", "escalation_due")
        else None
    )

    tender_service = TenderService()
    tender_order_plus_products = tender_service.read_order(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not tender_order_plus_products:
        if is_tender_created:
            raise WorkflowException(BusinessError.TENDER_NOT_FOUND)
        logger.warning("read_tender_row failed tender_id=%s", tender_id)
        return state

    order = tender_order_plus_products["tender"]
    if not is_tender_created and parse_tender_date(order.get("delivery_date")) is None:
        raise WorkflowException(BusinessError.MISSING_DELIVERY_DATE)

    set_tender(
        state.data,
        tender_from_read_order(
            tender_order_plus_products,
            get_tender(state.data),
        ),
    )

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    lifecycle = None
    if wl_id:
        workflow_lifecycle_service = WorkflowLifecycleService()
        lifecycle = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
        if lifecycle:
            state.data["workflow_lifecycle_status"] = lifecycle.get("status") or ""
            lifecycle_meta = lifecycle.get("metadata")
            if isinstance(lifecycle_meta, dict):
                state.data["workflow_lifecycle_metadata"] = lifecycle_meta
                if routing_guide_has_attempt(lifecycle_meta):
                    sync_routing_guide_attempt_to_state(
                        state.data,
                        attempt=routing_guide_attempt_from_metadata(lifecycle_meta),
                    )

    load_type = resolve_load_type(state)
    if mark_stale_routing_guide_reminder_if_needed(
        data=state.data,
        event_type=event_type,
        payload_attempt=scheduled_routing_guide_attempt,
        lifecycle_metadata=(lifecycle or {}).get("metadata"),
        is_ftl=is_ftl_load_type(load_type),
    ):
        logger.info(
            "read_tender_row skipping stale routing-guide reminder "
            "event_type=%s payload_attempt=%s live_attempt=%s tender_id=%s",
            event_type,
            scheduled_routing_guide_attempt,
            routing_guide_attempt_from_metadata((lifecycle or {}).get("metadata")),
            tender_id,
        )
        return state

    if is_tender_created:
        domestic_cfg = gelita_domestic_delivery_settings(state)
        if domestic_cfg is None:
            raise WorkflowException(SystemError.MISSING_TENANT_SETTINGS_DOMESTIC_DELIVERY)
        state.data["is_domestic_delivery"] = domestic_cfg.is_domestic_delivery_country(
            _delivery_country_from_order(order)
        )
        skip_cfg = gelita_skipped_pack_codes_settings(state)
        skipped = frozenset(skip_cfg.pack_codes)
        state.data["skipped_pack_codes"] = list(skipped)
        state.data.pop("matched_skipped_pack_code", None)
        if skipped:
            tender = get_tender(state.data) or {}
            for product in get_tender_products(tender):
                pack_code = pack_code_for_product_gap(product)
                if pack_code in skipped:
                    state.data["matched_skipped_pack_code"] = pack_code
                    break

    return state
