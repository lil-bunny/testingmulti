"""Node: escalation_due — notify operations by email, set escalated sub_status."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.load_tendering_settings import (
    action_settings,
    gelita_escalate_tender_settings,
    is_ftl_load_type,
    resolve_load_type,
)
from app.domain.load_tendering_state import order_number_from_data
from app.domain.activity_log_descriptions import format_escalation_sent_action
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.tender_service import TenderService
from app.services.unipile_service import UnipileException
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService
from app.tools.communication_metadata import stash_communication_id
from app.tools.email import send_email
from app.tools.load_tendering_lifecycle_guards import (
    delayed_workflow_step_skip_reason,
    skip_sub_statuses_from_state,
)

logger = get_logger(__name__)


def _lifecycle_skip(
    state: Any,
    *,
    workflow_lifecycle_service: WorkflowLifecycleService,
    wl_id: str,
) -> str | None:
    row = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
    return delayed_workflow_step_skip_reason(
        row,
        skip_sub_statuses=skip_sub_statuses_from_state(state),
    )


def _resolve_order_number(
    state: Any,
    *,
    tenant_id: str,
    tender_id: str,
) -> str:
    """Prefer hydrated state; fall back to tender row (reject→exhausted never hits read_tender_row)."""
    order_number = order_number_from_data(state.data)
    if order_number:
        return order_number
    if not tender_id:
        return ""
    tender_service = TenderService()
    bundle = tender_service.read_order(tenant_id=tenant_id, tender_id=tender_id)
    if not bundle:
        return ""
    order_number = str(bundle["tender"].get("order_number") or "").strip()
    if order_number:
        state.data["order_number"] = order_number
    return order_number


def escalate_tender(state):
    """
    ``escalation_due``: notify operations by email (TO/body from ``tenant_settings``), then set
    lifecycle ``sub_status`` to ``escalated`` and append activity log when send succeeds.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    run_id = str(state.execution_id or "").strip() or None

    if not wl_id or not tenant_id:
        logger.warning("escalate_tender missing workflow_lifecycle_id or tenant_id")
        state.data["escalation_email_error"] = "missing_workflow_lifecycle_id_or_tenant"
        state.data["escalation_email_sent"] = False
        return state

    workflow_lifecycle_service = WorkflowLifecycleService()
    # Always revoke pending ETAs on escalate entry (including already-escalated re-entry).
    reminder_cancel_service = WorkflowReminderCancelService()
    reminder_cancel_service.cancel_all(lifecycle_id=wl_id)

    skip = _lifecycle_skip(
        state,
        workflow_lifecycle_service=workflow_lifecycle_service,
        wl_id=wl_id,
    )
    if skip:
        logger.info(
            "escalate_tender skipping before send lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["escalation_skipped"] = skip
        state.data["escalation_email_sent"] = False
        return state

    load_type = resolve_load_type(state)
    escalate_cfg = gelita_escalate_tender_settings(state, load_type=load_type)
    if escalate_cfg is None:
        logger.error("escalate_tender invalid escalate_tender tenant settings")
        state.data["escalation_email_error"] = "invalid_tenant_settings_escalate_tender"
        state.data["escalation_email_sent"] = False
        return state

    merged = action_settings(state, "escalate_tender", load_type=load_type)
    recipients = escalate_cfg.recipients()
    account_id = str(merged.get("ana_at_gelita_account_id") or "").strip()
    if not account_id:
        state.data["escalation_email_error"] = "missing_sender_account_id"
        state.data["escalation_email_sent"] = False
        logger.error(
            "escalate_tender: no sender account id (ANA_AT_GELITA_ACCOUNT_ID / fallback) tender_id=%s",
            tender_id or None,
        )
        return state

    order_number = _resolve_order_number(
        state,
        tenant_id=tenant_id,
        tender_id=tender_id,
    )

    fmt_ctx = {"order_number": order_number or "unknown"}
    subject_template = escalate_cfg.escalation_email_subject.strip()
    body_template = escalate_cfg.escalation_email_body.strip()
    if not subject_template:
        subject_template = "Gelita tender escalation (order {order_number})"
    if not body_template:
        load_label = "FTL" if is_ftl_load_type(load_type) else "LTL"
        body_template = f"{load_label} escalation for order {{order_number}}"

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
            to=recipients.to,
            cc=recipients.cc,
            bcc=recipients.bcc,
            subject=subject,
            body=body,
            account_id=account_id,
            tenant_id=tenant_id,
            workflow_run_id=run_id,
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

    communication_id = stash_communication_id(state, result if isinstance(result, dict) else None)

    skip = _lifecycle_skip(
        state,
        workflow_lifecycle_service=workflow_lifecycle_service,
        wl_id=wl_id,
    )
    if skip:
        logger.info(
            "escalate_tender skipping after send (no lifecycle update) lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["escalation_skipped"] = skip
        return state

    if not run_id:
        logger.warning(
            "escalate_tender success path skipped lifecycle update: missing execution_id lifecycle_id=%s",
            wl_id,
        )
        return state

    row_after_send = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
    current_status = status_type_from_db(row_after_send.get("status")) if row_after_send else None
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        transition_step = ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_sub_status=StatusSubType.ESCALATED,
        )
    else:
        transition_step = ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=StatusSubType.ESCALATED,
        )

    activity_log_service = ActivityLogService()
    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_escalation_sent_action(),
                    communication_id=communication_id,
                ),
                transition_step,
            ),
        )
    )

    state.data["escalation_sub_status"] = StatusSubType.ESCALATED.value
    return state
