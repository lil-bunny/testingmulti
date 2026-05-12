from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.tasks.reminders import trigger_pod_reminder


def _reminder_offset_label(hours: float) -> str:
    """Human-readable offset for reminder subject lines (supports sub-hour .env values)."""
    h = float(hours)
    if h <= 0:
        return "0h"
    total_sec = h * 3600.0
    if total_sec < 90:
        s = max(1, int(round(total_sec)))
        return f"{s}s"
    if h < 1.0:
        m = max(1, int(round(h * 60.0)))
        return f"{m}m"
    if abs(h - round(h)) < 1e-9:
        return f"{int(round(h))}h"
    return f"{h:g}h"


def _build_reminder_payload(
    data: dict[str, Any], reminder_hours: float, reminder_step: int
) -> dict[str, Any]:
    step = int(reminder_step)
    if step == 0:
        subject = (data.get("subject") or "").strip() or "POD Request"
    else:
        # Do not reuse route_completed ``subject``; follow-ups label the offset for this step.
        subject = f"POD Reminder ({_reminder_offset_label(reminder_hours)})"
    payload = {
        "event_type": "reminder_due",
        "reminder_step": step,
        "tenant_id": data.get("tenant_id"),
        "workflow_lifecycle_id": data.get("workflow_lifecycle_id"),
        "shipment_id": data.get("shipment_id"),
        "load_id": data.get("load_id"),
        "thread_id": data.get("thread_id"),
        "account_id": data.get("account_id"),
        "to": data.get("to"),
        "subject": subject,
        "body": (data.get("body") or "").strip()
        or settings.POD_REMINDER_EMAIL_BODY,
    }
    return payload


def schedule_pod_reminders(data: dict[str, Any]) -> None:
    """
    After initial route_completed (POD missing), enqueue three Celery runs:
    REMINDER_0_HOURS, REMINDER_1_HOURS, REMINDER_2_HOURS (steps 0–2), in **hours** (fractional OK).
    Each run uses event_type=reminder_due; the graph re-checks Turvo before send.
    """
    if data.get("event_type") != "route_completed":
        return
    if data.get("reminders_scheduled"):
        return
    if not data.get("workflow_lifecycle_id") or not data.get("tenant_id"):
        return

    specs: list[tuple[float, int]] = [
        (float(settings.REMINDER_0_HOURS), 0),
        (float(settings.REMINDER_1_HOURS), 1),
        (float(settings.REMINDER_2_HOURS), 2),
    ]
    max_cd_hours = max(h for h, _ in specs)
    expire_s = int(
        (
            timedelta(hours=max_cd_hours)
            + timedelta(hours=settings.REMINDER_EXPIRE_GRACE_HOURS)
        ).total_seconds()
    )

    queued_ids: list[Any] = []
    try:
        for hours, step in specs:
            payload = _build_reminder_payload(data, hours, step)
            r = trigger_pod_reminder.apply_async(
                kwargs={"payload": payload},
                countdown=timedelta(hours=hours).total_seconds(),
                expires=expire_s,
            )
            queued_ids.append(r)
    except Exception:
        for r in queued_ids:
            try:
                r.revoke(terminate=False)
            except Exception:
                pass
        return

    data["reminders_scheduled"] = True


# Backwards-compatible name for callers/tests expecting the old symbol.
schedule_initial_pod_reminders = schedule_pod_reminders
