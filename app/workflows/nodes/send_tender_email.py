"""Node: send initial tender email to vendor."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.gelita.routing_guide_lifecycle import routing_guide_attempt_from_state
from app.domain.load_tendering_settings import (
    action_settings,
    gelita_send_tender_email_settings,
    is_ftl_load_type,
)
from app.domain.ingest_source_fields import delivery_gap_context
from app.domain.load_tendering_state import (
    get_tender,
    get_tender_products,
    load_type_from_data,
)
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.domain.tender_business_warnings import (
    append_tender_business_warning,
    format_reason_for_failure_html,
    get_tender_business_warnings,
)
from app.tools.routing_guide_carrier import (
    build_carrier_note_from_resolution,
    resolve_carrier_for_tender,
)
from app.tools.email import send_email
from app.tools.tender_email import (
    build_ftl_tender_email_from_tender,
    build_ltl_tender_email_from_tender,
    is_missing_address_value,
)
from app.workflows.utils.decorators import safe_node
from app.workflows.utils.gelita_soft_fail import record_business_gap_or_raise

logger = get_logger(__name__)


class SendTenderEmailError(Exception):
    """``send_tender_email`` failed; raised to terminate the workflow run."""


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
    if parse_tender_date(tender.get("delivery_date")) is None:
        record_business_gap_or_raise(state.data, BusinessError.MISSING_DELIVERY_DATE)
        tender["delivery_date"] = "Missing delivery date"
    if is_missing_address_value(tender.get("pickup_address")):
        record_business_gap_or_raise(state.data, BusinessError.MISSING_PICKUP_ADDRESS)
        tender["pickup_address"] = ""
    if is_missing_address_value(tender.get("delivery_address")):
        delivery_ctx = delivery_gap_context(tender, state.data)
        record_business_gap_or_raise(
            state.data,
            BusinessError.MISSING_DELIVERY_ADDRESS,
            **delivery_ctx,
        )
        tender["delivery_address"] = ""

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

    carrier_note = ""
    if ftl:
        attempt = routing_guide_attempt_from_state(state.data)
        tenant_id = str(getattr(state, "tenant_id", None) or state.data.get("tenant_id") or "").strip()
        tenant_slug = str(
            getattr(state, "tenant_slug", None) or state.data.get("tenant_slug") or ""
        ).strip() or None
        resolution = resolve_carrier_for_tender(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tender=tender,
            attempt=attempt,
        )
        if resolution.lane_miss:
            append_tender_business_warning(
                state.data,
                code=BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND.value,
                message=format_error_message(BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND),
            )
        elif resolution.missing_carrier_email:
            append_tender_business_warning(
                state.data,
                code=BusinessError.MISSING_ROUTING_GUIDE_CARRIER_EMAIL.value,
                message=format_error_message(
                    BusinessError.MISSING_ROUTING_GUIDE_CARRIER_EMAIL,
                    plan_carrier=resolution.plan_carrier_name or f"attempt {attempt}",
                ),
            )
        carrier_note = build_carrier_note_from_resolution(
            attempt=attempt,
            resolution=resolution,
        )

    reason_for_failure = format_reason_for_failure_html(
        get_tender_business_warnings(state.data)
    )

    recipients = email_cfg.recipients()
    if ftl:
        built = build_ftl_tender_email_from_tender(
            tender,
            template,
            subject_template,
            reason_for_failure=reason_for_failure,
            carrier_note=carrier_note,
        )
    else:
        built = build_ltl_tender_email_from_tender(
            tender,
            template,
            subject_template,
            reason_for_failure=reason_for_failure,
        )

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
