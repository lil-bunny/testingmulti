"""Enqueue Gelita ``load_tendering`` reminder / escalation runs via Celery (ETA pattern)."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.domain.load_tendering_settings import (
    action_settings,
    is_ftl_load_type,
    resolve_load_type,
)
from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.services.lifecycle_transition_service import LifecycleTransitionService
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
        StatusSubType.DO_NOTHING.value,
    }
)


def _reminder_schedule_specs(
    data: dict[str, Any], load_type: str
) -> list[tuple[float, str, int | None]]:
    """
    Return Celery ETA specs as ``(hours, event_type, reminder_step)``.

    FTL: one reminder (step 1) then escalation. LTL: two reminders then escalation.
    """
    reminder_cfg = action_settings(data, "send_tender_reminder", load_type=load_type)
    escalation_cfg = action_settings(data, "escalate_tender", load_type=load_type)
    if is_ftl_load_type(load_type):
        return [
            (float(reminder_cfg["reminder_1_hours"]), "reminder_due", 1),
            (float(escalation_cfg["escalation_hours"]), "escalation_due", None),
        ]
    return [
        (float(reminder_cfg["reminder_1_hours"]), "reminder_due", 1),
        (float(reminder_cfg["reminder_2_hours"]), "reminder_due", 2),
        (float(escalation_cfg["escalation_hours"]), "escalation_due", None),
    ]


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
    After ``carrier_email_received``, enqueue delayed ``WorkflowService.run`` calls for
    ``load_tendering`` with ``reminder_due`` and ``escalation_due`` (LTL: two reminders;
    FTL: one reminder at 24h, escalation at 28h).

    Idempotent: skips if lifecycle has already progressed past ``tender_sent_to_carrier``
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

    load_type = resolve_load_type(data)
    try:
        specs = _reminder_schedule_specs(data, load_type)
    except (KeyError, TypeError, ValueError):
        logger.error(
            "schedule_tender_reminders missing reminder/escalation hours in tenant_settings "
            "lifecycle_id=%s",
            wl_id,
        )
        return
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
    if run_id:
        try:
            lifecycle_transition_service = LifecycleTransitionService()
            lifecycle_transition_service.apply(
                LifecycleTransitionCommand(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    activity_type=ActivityType.ACTION,
                    description=(
                        "Queued reminder_due and escalation_due Celery tasks "
                        f"(load_type={load_type or 'unknown'})"
                    ),
                    actor_type=ActorType.SYSTEM,
                    metadata={
                        "hours": [h for h, _, _ in specs],
                        "load_type": load_type or None,
                    },
                    update_lifecycle=False,
                )
            )
        except Exception:
            logger.exception(
                "schedule_tender_reminders activity log failed lifecycle_id=%s "
                "(tasks queued)",
                wl_id,
            )

    data["reminders_scheduled"] = True
