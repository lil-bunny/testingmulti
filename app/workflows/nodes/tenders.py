"""Nodes for Tenders table."""

from app.core.logger import get_logger
from app.domain.error_catalog import BusinessError
from app.domain.load_tendering_state import get_tender, set_tender, tender_from_read_order
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.workflows.utils.decorators import safe_node

logger = get_logger(__name__)


@safe_node
def read_tender_row(state):
    """Load order + product lines into ``state.data['tender']`` for reminder/escalation."""
    tender_id = str(state.data.get("tender_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()

    tender_service = TenderService()
    tender_order_plus_products = tender_service.read_order(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not tender_order_plus_products:
        logger.warning("read_tender_row failed tender_id=%s", tender_id)
        return state

    order = tender_order_plus_products["tender"]
    if parse_tender_date(order.get("delivery_date")) is None:
        raise WorkflowException(BusinessError.MISSING_DELIVERY_DATE)

    set_tender(
        state.data,
        tender_from_read_order(
            tender_order_plus_products,
            get_tender(state.data),
        ),
    )

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    if wl_id:
        workflow_lifecycle_service = WorkflowLifecycleService()
        lifecycle = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
        if lifecycle:
            state.data["workflow_lifecycle_status"] = lifecycle.get("status") or ""

    return state
