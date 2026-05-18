"""Nodes for Tenders table."""
from app.core import logger
from app.services.tender_service import TenderService

def read_tender_row(state):
    """Read tender row from Tenders table and return it."""
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
    return state