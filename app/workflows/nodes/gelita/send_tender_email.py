"""Node: send initial tender email to vendor."""

from __future__ import annotations

import app.configs.gelita_config as gelita_config
from app.core.logger import get_logger
from app.services.unipile_service import UnipileException
from app.tools.email import send_email
from app.workflows.nodes.gelita.load_tendering_helpers import build_gelita_tender_email

logger = get_logger(__name__)


def send_tender_email(state):
    account_id = gelita_config.ANA_GELITA_AT_FREIGHTX_AI_ACCOUNT_ID

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
        built = build_gelita_tender_email(
            tender_data,
            calculated,
            gelita_config.EMAIL_TEMPLATE_HTML,
        )
        result = send_email(
            to=gelita_config.VENDOR_EMAIL,
            subject=built["subject"],
            body=built["body_html"],
            account_id=account_id,
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
