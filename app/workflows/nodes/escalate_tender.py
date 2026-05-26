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
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.unipile_service import UnipileException
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.communication_metadata import outbound_email_metadata, stash_communication_id
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

    tender_row = state.data.get("tender_row")
    order_number = str(state.data.get("order_number") or "").strip()
    if not order_number and isinstance(tender_row, dict):
        order_number = str(tender_row.get("order_number") or "").strip()

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

    comm_id = stash_communication_id(state, result if isinstance(result, dict) else None)

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

    email_meta = outbound_email_metadata(
        to=recipients.to,
        cc=recipients.cc,
        bcc=recipients.bcc,
    )
    log_metadata: dict[str, Any] = {
        "tender_id": tender_id or None,
        "order_number": order_number or None,
        **email_meta,
    }
    if comm_id:
        log_metadata["communication_id"] = comm_id

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_sub_status=StatusSubType.ESCALATED,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        description="Escalation email sent to operations",
        actor_type=ActorType.SYSTEM,
        metadata=log_metadata,
    )

    state.data["escalation_sub_status"] = StatusSubType.ESCALATED.value
    return state
