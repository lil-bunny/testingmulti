"""Node: escalation_due — notify operations by email, set escalated sub_status."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.load_tendering_settings import action_settings
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.unipile_service import UnipileException
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.email import send_email
from app.domain.status_parsing import status_type_from_db

logger = get_logger(__name__)


def escalate_tender(state):
    """
    ``escalation_due``: notify operations by email (TO/body from ``tenant_settings``), then set
    lifecycle ``sub_status`` to ``escalated`` and append activity log when send succeeds.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()

    if not wl_id or not tenant_id:
        logger.warning("escalate_tender missing workflow_lifecycle_id or tenant_id")
        state.data["escalation_email_error"] = "missing_workflow_lifecycle_id_or_tenant"
        state.data["escalation_email_sent"] = False
        return state

    lifecycle_svc = WorkflowLifecycleService()
    prev = lifecycle_svc.read_lifecycle_row_by_id(wl_id)
    if not prev:
        logger.warning("escalate_tender lifecycle not found id=%s", wl_id)
        state.data["escalation_email_error"] = "lifecycle_not_found"
        state.data["escalation_email_sent"] = False
        return state

    prev_status = status_type_from_db(prev.get("status"))

    if prev_status == StatusType.COMPLETED:
        logger.info(
            "escalate_tender skipping: lifecycle already completed lifecycle_id=%s",
            wl_id,
        )
        state.data["escalation_skipped"] = "lifecycle_already_completed"
        state.data["escalation_email_sent"] = False
        return state

    cfg = action_settings(state, "escalate_tender")
    to_addr = str(cfg.get("escalation_notify_email") or "").strip()
    if not to_addr or "@" not in to_addr:
        logger.error("escalate_tender ESCALATION_NOTIFY_EMAIL invalid or empty")
        state.data["escalation_email_error"] = "missing_escalation_notify_email"
        state.data["escalation_email_sent"] = False
        return state

    account_id = str(cfg.get("ana_at_gelita_account_id") or "").strip()
    if not account_id:
        state.data["escalation_email_error"] = "missing_sender_account_id"
        state.data["escalation_email_sent"] = False
        logger.error(
            "escalate_tender: no sender account id (ANA_AT_GELITA_ACCOUNT_ID / fallback) tender_id=%s",
            tender_id or None,
        )
        return state

    tender_row = state.data.get("tender_row")
    order_number = str(state.data.get("order_number") or "").strip()
    if not order_number and isinstance(tender_row, dict):
        order_number = str(tender_row.get("order_number") or "").strip()

    fmt_ctx = {
        "workflow_lifecycle_id": wl_id,
        "tender_id": tender_id or "unknown",
        "order_number": order_number or "unknown",
    }
    subject_template = str(cfg.get("escalation_email_subject") or "").strip()
    body_template = str(cfg.get("escalation_email_body") or "").strip()
    if not subject_template:
        subject_template = "Gelita tender escalation (order {order_number})"
    if not body_template:
        body_template = (
            "Escalation for tender_id={tender_id} lifecycle_id={workflow_lifecycle_id} "
            "order_number={order_number}"
        )

    subject = subject_template.format(**fmt_ctx)
    body = body_template.format(**fmt_ctx)

    logger.warning(
        "escalate_tender sending escalation email lifecycle_id=%s tender_id=%s",
        wl_id,
        tender_id or None,
    )

    result = None
    try:
        result = send_email(
            to=to_addr,
            subject=subject,
            body=body,
            account_id=account_id,
            tenant_id=tenant_id,
            communication_metadata={
                "source": "escalate_tender",
                "tender_id": tender_id or None,
                "workflow_lifecycle_id": wl_id,
            },
        )
    except UnipileException as exc:
        logger.warning(
            "escalate_tender Unipile error lifecycle_id=%s tender_id=%s: %s",
            wl_id,
            tender_id or None,
            exc,
        )
        state.data["escalation_email_result"] = result
        state.data["escalation_email_error"] = str(exc)
        state.data["escalation_email_sent"] = False
        return state
    except Exception:
        logger.exception(
            "escalate_tender unexpected error lifecycle_id=%s tender_id=%s",
            wl_id,
            tender_id or None,
        )
        state.data["escalation_email_result"] = result
        state.data["escalation_email_error"] = "unexpected_error"
        state.data["escalation_email_sent"] = False
        return state

    if result is None:
        state.data["escalation_email_error"] = "send_skipped_or_no_result"
        state.data["escalation_email_sent"] = False
        return state

    success = True
    if isinstance(result, dict):
        success = bool(result.get("success", True))
    state.data["escalation_email_result"] = result
    state.data["escalation_email_sent"] = success
    if not success:
        state.data["escalation_email_error"] = (
            (result or {}).get("error") if isinstance(result, dict) else None
        ) or "unipile_send_failed"
        return state

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_sub_status=StatusSubType.ESCALATED,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        description="Escalation email sent to operations",
        actor_type=ActorType.SYSTEM,
        metadata={
            "tender_id": tender_id or None,
            "order_number": order_number or None,
            "escalation_notify_email_domain": to_addr.split("@", 1)[-1]
            if "@" in to_addr
            else None,
        },
    )

    state.data["escalation_sub_status"] = StatusSubType.ESCALATED.value
    return state
