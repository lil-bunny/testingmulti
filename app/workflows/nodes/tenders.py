"""Nodes for Tenders table."""
from app.core.logger import get_logger
from app.services.tender_service import TenderService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)

def read_tender_row(state):
    """Read tender row and lifecycle status for reminder/escalation routing."""
    tender_id = str(state.data.get("tender_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()

    tender_svc = TenderService()
    row = tender_svc.read_row(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not row:
        logger.warning("read_tender_row failed tender_id=%s", tender_id)
        return state
    state.data["tender_row"] = row

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    if wl_id:
        lifecycle = WorkflowLifecycleService().read_lifecycle_row_by_id(wl_id)
        if lifecycle:
            state.data["workflow_lifecycle_status"] = lifecycle.get("status") or ""

    return state