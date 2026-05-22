"""Node: send initial tender email to vendor."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.load_tendering_settings import action_settings
from app.services.unipile_service import UnipileException
from app.tools.email import send_email
from app.workflows.nodes.gelita.load_tendering_helpers import build_gelita_tender_email

logger = get_logger(__name__)


def send_tender_email(state):
    cfg = action_settings(state, "send_tender_email")
    account_id = str(cfg.get("ana_gelita_at_freightx_ai_account_id") or "").strip()

    if not account_id:
        state.data["tender_email_error"] = "missing_sender_account_id"
        logger.error("send_tender_email: ANA_AT_GELITA_ACCOUNT_ID / fallback account id not configured")
        return state

    tender_data = {
        "order_number": state.data.get("order_number"),
        "customer_po": state.data.get("customer_po"),
        "ship_date": state.data.get("ship_date"),
        "product_name": state.data.get("product_name"),
        "pickup_address": state.data.get("pickup_address"),
        "delivery_address": state.data.get("delivery_address"),
    }
    calculated = {
        "pieces": state.data.get("pieces_count"),
        "pallets": state.data.get("pallets_count"),
        "gross_weight": state.data.get("gross_weight_lbs"),
    }

    result = None
    try:
        template = str(cfg.get("email_template_html") or "").strip()
        if not template:
            state.data["tender_email_error"] = "missing_tenant_settings_email_template_html"
            logger.error("send_tender_email: email_template_html not configured")
            return state
        vendor_email = str(cfg.get("vendor_email") or "").strip()
        if not vendor_email or "@" not in vendor_email:
            state.data["tender_email_error"] = "missing_tenant_settings_vendor_email"
            logger.error("send_tender_email: vendor_email not configured")
            return state
        built = build_gelita_tender_email(
            tender_data,
            calculated,
            template,
        )
        result = send_email(
            to=vendor_email,
            subject=built["subject"],
            body=built["body_html"],
            account_id=account_id,
            tenant_id=state.tenant_id,
            communication_metadata={
                "source": "send_tender_email",
                "tender_id": state.data.get("tender_id"),
                "workflow_lifecycle_id": state.data.get("workflow_lifecycle_id"),
            },
        )
    except UnipileException as e:
        logger.warning(
            "send_tender_email Unipile error tender_id=%s: %s",
            state.data.get("tender_id"),
            e,
        )
        state.data["tender_email_result"] = result
        state.data["tender_email_error"] = str(e)
        state.data["tender_email_sent"] = False
        return state
    except Exception:
        logger.exception(
            "send_tender_email unexpected error tender_id=%s",
            state.data.get("tender_id"),
        )
        state.data["tender_email_result"] = result
        state.data["tender_email_error"] = "unexpected_error"
        state.data["tender_email_sent"] = False
        return state

    state.data["tender_email_result"] = result
    state.data["tender_email_sent"] = bool(result and result.get("success", False))
    return state
