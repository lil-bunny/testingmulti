from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.tasks.reminders import trigger_pod_reminder


def _build_reminder_payload(
    data: dict[str, Any], reminder_hours: int, reminder_step: int
) -> dict[str, Any]:
    payload = {
        "event_type": "reminder_due",
        "reminder_step": reminder_step,
        "tenant_id": data.get("tenant_id"),
        "workflow_instance_id": data.get("workflow_instance_id"),
        "shipment_id": data.get("shipment_id"),
        "load_id": data.get("load_id"),
        "thread_id": data.get("thread_id"),
        "to": data.get("to"),
        "subject": data.get("subject", f"POD Reminder ({reminder_hours}h)"),
        "body": (data.get("body") or "").strip()
        or settings.POD_REMINDER_EMAIL_BODY,
    }
    return payload


def schedule_initial_pod_reminders(data: dict[str, Any]) -> None:
    """
    Schedule the two reminder invocations (24h, 48h) after initial POD request.
    """
    if data.get("event_type") != "route_completed":
        return
    if data.get("reminders_scheduled"):
        return
    if not data.get("workflow_instance_id") or not data.get("tenant_id"):
        return

    first_payload = _build_reminder_payload(data, settings.REMINDER_1_HOURS, 1)
    second_payload = _build_reminder_payload(data, settings.REMINDER_2_HOURS, 2)

    queued_ids: list[Any] = []
    try:
        r1 = trigger_pod_reminder.apply_async(
            kwargs={"payload": first_payload},
            countdown=timedelta(hours=settings.REMINDER_1_HOURS).total_seconds(),
            expires=timedelta(hours=settings.REMINDER_EXPIRE_GRACE_HOURS),
        )
        queued_ids.append(r1)
        r2 = trigger_pod_reminder.apply_async(
            kwargs={"payload": second_payload},
            countdown=timedelta(hours=settings.REMINDER_2_HOURS).total_seconds(),
            expires=timedelta(hours=settings.REMINDER_EXPIRE_GRACE_HOURS),
        )
        queued_ids.append(r2)
    except Exception:
        # Avoid split state: first enqueue OK, second fails → revoke any queued work.
        for r in queued_ids:
            try:
                r.revoke(terminate=False)
            except Exception:
                pass
        # Keep workflow path non-blocking when broker is unavailable.
        return

    data["reminders_scheduled"] = True
