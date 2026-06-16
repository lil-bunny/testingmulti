"""Node: send initial tender email to vendor."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.error_catalog import BusinessError
from app.domain.load_tendering_settings import (
    action_settings,
    gelita_send_tender_email_settings,
    is_ftl_load_type,
)
from app.domain.load_tendering_state import get_tender, get_tender_products, load_type_from_data
from app.exceptions import WorkflowException
from app.tools.email import send_email
from app.tools.tender_email import (
    build_ftl_tender_email_from_tender,
    build_ltl_tender_email_from_tender,
)
from app.workflows.utils.decorators import safe_node

logger = get_logger(__name__)


class SendTenderEmailError(Exception):
    """``send_tender_email`` failed; raised to terminate the workflow run."""


def _missing_address(value: Any) -> bool:
    return not str(value or "").strip()


@safe_node
def send_tender_email(state):
    load_type = load_type_from_data(state.data)
    ftl = is_ftl_load_type(load_type)
    email_cfg = gelita_send_tender_email_settings(state, load_type=load_type)
    if email_cfg is None:
        msg = (
            f"invalid tenant settings load_type={load_type or 'unknown'}"
        )
        logger.error("send_tender_email: %s", msg)
        raise SendTenderEmailError(msg)

    merged = action_settings(state, "send_tender_email", load_type=load_type)
    account_id = str(merged.get("ana_at_gelita_account_id") or "").strip()
    if not account_id:
        msg = "missing_sender_account_id"
        logger.error("send_tender_email: %s", msg)
        raise SendTenderEmailError(msg)

    tender = dict(get_tender(state.data) or {})
    if _missing_address(tender.get("pickup_address")):
        raise WorkflowException(BusinessError.MISSING_PICKUP_ADDRESS)
    if _missing_address(tender.get("delivery_address")):
        raise WorkflowException(BusinessError.MISSING_DELIVERY_ADDRESS)

    if not get_tender_products(tender):
        msg = f"missing tender_products for tender_id={state.data.get('tender_id')}"
        logger.error("send_tender_email: %s", msg)
        raise SendTenderEmailError(msg)

    template = email_cfg.email_template_html.strip()
    if not template:
        msg = (
            f"missing email_template_html for load_type={load_type or 'unknown'}"
        )
        logger.error("send_tender_email: %s", msg)
        raise SendTenderEmailError(msg)

    subject_template = email_cfg.email_subject.strip()
    if not subject_template:
        msg = (
            f"missing email_subject for load_type={load_type or 'unknown'}"
        )
        logger.error("send_tender_email: %s", msg)
        raise SendTenderEmailError(msg)

    recipients = email_cfg.recipients()
    if ftl:
        built = build_ftl_tender_email_from_tender(tender, template, subject_template)
    else:
        built = build_ltl_tender_email_from_tender(tender, template, subject_template)

    run_id = str(state.execution_id or "").strip() or None
    result = send_email(
        to=recipients.to,
        cc=recipients.cc,
        bcc=recipients.bcc,
        subject=built["subject"],
        body=built["body_html"],
        account_id=account_id,
        tenant_id=state.tenant_id,
        workflow_run_id=run_id,
        communication_metadata={
            "source": "send_tender_email",
            "tender_id": state.data.get("tender_id"),
            "workflow_lifecycle_id": state.data.get("workflow_lifecycle_id"),
            "load_type": load_type,
        },
    )
    if not result or not result.get("success"):
        err = (result or {}).get("error") if isinstance(result, dict) else None
        msg = str(err or "tender email send failed")
        logger.error(
            "send_tender_email failed tender_id=%s: %s",
            state.data.get("tender_id"),
            msg,
        )
        raise SendTenderEmailError(msg)

    state.data["tender_email_result"] = result
    state.data["tender_email_sent"] = True
    comm_id = result.get("communication_id")
    if comm_id:
        state.data["communication_id"] = str(comm_id)
    return state
