"""Node: in-thread reminder on the carrier conversation via Unipile."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.gelita.routing_guide_lifecycle import routing_guide_attempt_from_state
from app.domain.load_tendering_settings import action_settings, is_ftl_load_type, resolve_load_type
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.services.unipile_service import UnipileException
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.communication_metadata import stash_communication_id
from app.tools.email import reply_to_thread
from app.tools.load_tendering_lifecycle_guards import (
    delayed_workflow_step_skip_reason,
    skip_sub_statuses_from_state,
    stale_ftl_routing_guide_reminder,
)

logger = get_logger(__name__)


def send_tender_reminder(state):
    """
    In-thread reminder on the carrier conversation: resolve thread via comms + runs
    (``carrier_email_received`` anchor), then reply via Unipile.
    """
    workflow_lifecycle_id_str = str(state.data.get("workflow_lifecycle_id") or "").strip()
    if not workflow_lifecycle_id_str:
        logger.warning("send_tender_reminder missing workflow_lifecycle_id on state")
        state.data["tender_reminder_error"] = "missing_workflow_lifecycle_id"
        state.data["tender_reminder_sent"] = False
        return state

    lifecycle_svc = WorkflowLifecycleService()
    lifecycle_row = lifecycle_svc.read_lifecycle_row_by_id(workflow_lifecycle_id_str)
    skip = delayed_workflow_step_skip_reason(
        lifecycle_row,
        skip_sub_statuses=skip_sub_statuses_from_state(state),
    )
    if skip:
        logger.info(
            "send_tender_reminder skipping lifecycle_id=%s reason=%s",
            workflow_lifecycle_id_str,
            skip,
        )
        state.data["tender_reminder_skipped"] = skip
        state.data["tender_reminder_sent"] = False
        return state

    load_type = resolve_load_type(state)
    is_ftl = is_ftl_load_type(load_type)

    if stale_ftl_routing_guide_reminder(state):
        logger.info(
            "send_tender_reminder skipping stale routing-guide reminder lifecycle_id=%s",
            workflow_lifecycle_id_str,
        )
        state.data["tender_reminder_skipped"] = "stale_routing_guide_reminder"
        state.data["tender_reminder_sent"] = False
        return state

    attempt = routing_guide_attempt_from_state(state.data) if is_ftl else None
    communications_service = CommunicationsService()
    lifecycle_email_thread_id = communications_service.resolve_thread_for_lifecycle(
        tenant_id=state.tenant_id or "",
        workflow_lifecycle_id=workflow_lifecycle_id_str,
        anchor_event_type=WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
        routing_guide_attempt=attempt,
    )

    if not lifecycle_email_thread_id:
        logger.warning(
            "send_tender_reminder no carrier thread via comms lifecycle_id=%s",
            workflow_lifecycle_id_str,
        )
        state.data["tender_reminder_error"] = "missing_email_thread_id"
        state.data["tender_reminder_sent"] = False
        return state

    cfg = action_settings(state, "send_tender_reminder", load_type=load_type)
    sender_account_id = str(cfg.get("ana_at_gelita_account_id") or "").strip()
    if not sender_account_id:
        state.data["tender_reminder_error"] = "missing_ANA_AT_GELITA_ACCOUNT_ID"
        state.data["tender_reminder_sent"] = False
        logger.error(
            "send_tender_reminder: ANA_AT_GELITA_ACCOUNT_ID not configured (tender_id=%s)",
            state.data.get("tender_id"),
        )
        return state

    reminder_body_plain = str(cfg.get("reminder_body") or "").strip() or (
        "Following up on the tender request."
    )
    run_id = str(state.execution_id or "").strip() or None

    reminder_send_result = None
    try:
        reminder_send_result = reply_to_thread(
            thread_id=lifecycle_email_thread_id,
            body=reminder_body_plain,
            account_id=sender_account_id,
            subject=None,
            tenant_id=state.tenant_id,
            workflow_run_id=run_id,
            communication_metadata={
                "source": "send_tender_reminder",
                "tender_id": state.data.get("tender_id"),
                "workflow_lifecycle_id": workflow_lifecycle_id_str,
            },
        )
    except UnipileException as exc:
        logger.warning(
            "send_tender_reminder Unipile error tender_id=%s thread_id=%s: %s",
            state.data.get("tender_id"),
            lifecycle_email_thread_id,
            exc,
        )
        state.data["tender_reminder_result"] = reminder_send_result
        state.data["tender_reminder_error"] = str(exc)
        state.data["tender_reminder_sent"] = False
        return state
    except Exception:
        logger.exception(
            "send_tender_reminder unexpected error tender_id=%s",
            state.data.get("tender_id"),
        )
        state.data["tender_reminder_result"] = reminder_send_result
        state.data["tender_reminder_error"] = "unexpected_error"
        state.data["tender_reminder_sent"] = False
        return state

    stash_communication_id(
        state,
        reminder_send_result if isinstance(reminder_send_result, dict) else None,
    )

    state.data["tender_reminder_result"] = reminder_send_result
    success = True
    if isinstance(reminder_send_result, dict):
        success = bool(reminder_send_result.get("success", True))
    state.data["tender_reminder_sent"] = success
    if not success:
        state.data["tender_reminder_error"] = (
            (reminder_send_result or {}).get("error")
            if isinstance(reminder_send_result, dict)
            else None
        ) or "unipile_send_failed"
    return state
