"""Node: in-thread reminder on the carrier conversation via Unipile."""

from __future__ import annotations

import app.configs.gelita_config as gelita_config
from app.core.logger import get_logger
from app.services.unipile_service import UnipileException
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.email import reply_to_thread

logger = get_logger(__name__)


def send_tender_reminder(state):
    """
    In-thread reminder on the carrier conversation: use ``email_thread_id`` persisted on the
    workflow lifecycle row only, then reply via Unipile.
    """
    workflow_lifecycle_id_str = str(state.data.get("workflow_lifecycle_id") or "").strip()
    if not workflow_lifecycle_id_str:
        logger.warning("send_tender_reminder missing workflow_lifecycle_id on state")
        state.data["tender_reminder_error"] = "missing_workflow_lifecycle_id"
        state.data["tender_reminder_sent"] = False
        return state

    lifecycle_svc = WorkflowLifecycleService()
    lifecycle_row = lifecycle_svc.read_lifecycle_row_by_id(workflow_lifecycle_id_str)
    if not lifecycle_row:
        logger.warning(
            "send_tender_reminder lifecycle not found id=%s",
            workflow_lifecycle_id_str,
        )
        state.data["tender_reminder_error"] = "lifecycle_not_found"
        state.data["tender_reminder_sent"] = False
        return state

    lifecycle_email_thread_id = str(lifecycle_row.get("email_thread_id") or "").strip()

    if not lifecycle_email_thread_id:
        logger.warning(
            "send_tender_reminder lifecycle has no email_thread_id lifecycle_id=%s",
            workflow_lifecycle_id_str,
        )
        state.data["tender_reminder_error"] = "missing_email_thread_id"
        state.data["tender_reminder_sent"] = False
        return state

    gelita_sender_account_id = str(gelita_config.GELITA_SENDER_ACCOUNT_ID or "").strip()
    if not gelita_sender_account_id:
        state.data["tender_reminder_error"] = "missing_gelita_sender_account_id"
        state.data["tender_reminder_sent"] = False
        logger.error(
            "send_tender_reminder: GELITA_SENDER_ACCOUNT_ID not configured (tender_id=%s)",
            state.data.get("tender_id"),
        )
        return state

    reminder_body_plain = str(gelita_config.REMINDER_BODY or "").strip() or (
        "Following up on the tender request."
    )

    reminder_send_result = None
    try:
        reminder_send_result = reply_to_thread(
            thread_id=lifecycle_email_thread_id,
            body=reminder_body_plain,
            account_id=gelita_sender_account_id,
            subject=None,
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

    state.data["tender_reminder_result"] = reminder_send_result
    success = True
    if isinstance(reminder_send_result, dict):
        success = bool(reminder_send_result.get("success", True))
    state.data["tender_reminder_sent"] = success
    if not success:
        state.data["tender_reminder_error"] = (
            (reminder_send_result or {}).get("error") if isinstance(reminder_send_result, dict) else None
        ) or "unipile_send_failed"
    return state
