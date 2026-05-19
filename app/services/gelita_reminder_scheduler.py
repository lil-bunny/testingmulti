"""Enqueue Gelita ``load_tendering`` reminder / escalation runs via Celery (ETA pattern)."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

import app.configs.gelita_config as gelita_config
from app.core.config import settings
from app.core.logger import get_logger
from app.models.status import StatusSubType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.reminders import trigger_gelita_tender_reminder

logger = get_logger(__name__)

_SCHEDULE_SKIP_SUB_STATUSES = frozenset(
    {
        StatusSubType.REMINDER_1_SENT.value,
        StatusSubType.REMINDER_2_SENT.value,
        StatusSubType.ESCALATED.value,
        StatusSubType.ACCEPTED.value,
        StatusSubType.REJECTED.value,
    }
)


def _build_payload(
    base: dict[str, Any],
    *,
    event_type: str,
    reminder_step: int | None,
) -> dict[str, Any]:
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    out["event_type"] = event_type
    if reminder_step is not None:
        out["reminder_step"] = int(reminder_step)
    return out


def schedule_tender_reminders(data: dict[str, Any]) -> None:
    """
    After ``carrier_email_received``, enqueue three delayed ``WorkflowService.run`` calls
    for ``load_tendering`` with ``reminder_due`` (steps 1 and 2) and ``escalation_due``.

    Idempotent: skips if lifecycle has already progressed past ``awaiting_response``
    (reminder sent, escalated, or terminal ack).
    """
    if data.get("reminders_scheduled"):
        return
    if data.get("event_type") != "carrier_email_received":
        return

    wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = str(data.get("tenant_id") or "").strip()
    tenant_slug = str(data.get("tenant_slug") or "").strip()
    thread_id = str(data.get("thread_id") or data.get("email_thread_id") or "").strip()

    if not wl_id or not tenant_id or not tenant_slug or not thread_id:
        logger.warning(
            "schedule_tender_reminders missing ids wl_id=%s tenant_id=%s tenant_slug=%s thread_id=%s",
            bool(wl_id),
            bool(tenant_id),
            bool(tenant_slug),
            bool(thread_id),
        )
        return

    lifecycle_svc = WorkflowLifecycleService()
    row = lifecycle_svc.read_lifecycle_row_by_id(wl_id)
    if not row:
        logger.warning("schedule_tender_reminders lifecycle not found id=%s", wl_id)
        return
    current_sub = str(row.get("sub_status") or "").strip()
    if current_sub in _SCHEDULE_SKIP_SUB_STATUSES:
        data["reminders_scheduled"] = True
        return

    specs: list[tuple[float, str, float | None]] = [
        (gelita_config.REMINDER_1_HOURS, "reminder_due", 1),
        (gelita_config.REMINDER_2_HOURS, "reminder_due", 2),
        (gelita_config.ESCALATION_HOURS, "escalation_due", None),
    ]
    max_cd_hours = max(h for h, _, _ in specs)
    expire_s = int(
        (
            timedelta(hours=max_cd_hours)
            + timedelta(hours=settings.REMINDER_EXPIRE_GRACE_HOURS)
        ).total_seconds()
    )

    base_payload = {
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "workflow_lifecycle_id": wl_id,
        "tender_id": data.get("tender_id"),
        "thread_id": thread_id,
    }

    queued: list[Any] = []
    try:
        for h, et, step in specs:
            payload = _build_payload(base_payload, event_type=et, reminder_step=step)
            r = trigger_gelita_tender_reminder.apply_async(
                kwargs={"payload": payload},
                countdown=timedelta(hours=h).total_seconds(),
                expires=expire_s,
            )
            queued.append(r)
    except Exception:
        logger.exception("schedule_tender_reminders enqueue failed lifecycle_id=%s", wl_id)
        for r in queued:
            try:
                r.revoke(terminate=False)
            except Exception:
                pass
        return

    run_id = str(data.get("workflow_run_id") or "").strip() or None
    try:
        ActivityLogService().insert(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            activity_type="tender_reminders_scheduled",
            message="Queued reminder_due (1,2) and escalation_due Celery tasks",
            from_sub_status=current_sub or StatusSubType.AWAITING_RESPONSE,
            to_sub_status=StatusSubType.AWAITING_RESPONSE,
            payload={"hours": [h for h, _, _ in specs]},
        )
    except Exception:
        logger.exception(
            "schedule_tender_reminders activity log failed lifecycle_id=%s (tasks queued)",
            wl_id,
        )

    data["reminders_scheduled"] = True
