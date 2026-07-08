"""Schedule delayed workflow runs from ``tenant_settings[workflow_name].reminders``."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import ValidationError

from app.core.logger import get_logger
from app.domain.before_pickup_reminder_plan import plan_before_pickup_reminders
from app.domain.driver_assignment.guards import driver_assignment_reminder_skip_sub_statuses
from app.domain.load_tendering_settings import load_type_bucket, resolve_load_type
from app.domain.pod_lifecycle.guards import pod_reminder_skip_sub_statuses
from app.domain.reminder_schedule import ReminderStepSpec, WorkflowRemindersConfig
from app.domain.gelita.routing_guide_lifecycle import optional_routing_guide_attempt
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService
from app.tasks.reminders import trigger_workflow_reminder

logger = get_logger(__name__)

# Copied onto Celery payload when present in graph state (workflow-agnostic).
_DEFAULT_PAYLOAD_KEYS: tuple[str, ...] = (
    "tenant_id",
    "tenant_slug",
    "workflow_lifecycle_id",
    "tender_id",
    "thread_id",
    "shipment_id",
    "load_id",
    "shipments_row_id",
    "ratecon_workflow_lifecycle_id",
    "pickup_appointment_at",
    "pickup_appointment_timezone",
    "account_id",
    "to",
    "subject",
    "body",
    "routing_guide_attempt",
)

_REQUIRED_SCHEDULE_KEYS: tuple[str, ...] = (
    "workflow_lifecycle_id",
    "tenant_id",
)

_VARIANT_SELECTORS: dict[str, Callable[[dict[str, Any]], str]] = {
    "load_type": lambda data: load_type_bucket(resolve_load_type(data)),
}


def _reminder_offset_label(hours: float) -> str:
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


def _tenant_settings_root(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("tenant_settings")
    return raw if isinstance(raw, dict) else {}


def _reminder_skip_sub_statuses(
    workflow_name: str, reminders: WorkflowRemindersConfig
) -> frozenset[str]:
    wf = (workflow_name or "").strip()
    if wf == "pod_lifecycle":
        return pod_reminder_skip_sub_statuses()
    if wf == "driver_assignment":
        return driver_assignment_reminder_skip_sub_statuses()
    return frozenset(s.strip() for s in reminders.skip_sub_statuses if str(s).strip())


def parse_reminders_for_workflow(
    data: dict[str, Any], workflow_name: str
) -> WorkflowRemindersConfig | None:
    """Read and validate ``tenant_settings.<workflow_name>.reminders``."""
    wf = (workflow_name or "").strip()
    block = _tenant_settings_root(data).get(wf)
    if not isinstance(block, dict):
        logger.error(
            "workflow_reminder missing tenant_settings block workflow=%s",
            wf,
        )
        return None
    raw_reminders = block.get("reminders")
    if not isinstance(raw_reminders, dict):
        logger.error(
            "workflow_reminder missing reminders section workflow=%s",
            wf,
        )
        return None
    try:
        return WorkflowRemindersConfig.model_validate(raw_reminders)
    except ValidationError:
        logger.exception(
            "workflow_reminder invalid reminders config workflow=%s",
            wf,
        )
        return None


def _resolve_variant_key(
    reminders: WorkflowRemindersConfig, data: dict[str, Any], workflow_name: str
) -> str | None:
    selector = reminders.variant_selector
    if not selector:
        return None
    resolver = _VARIANT_SELECTORS.get(selector)
    if resolver is None:
        logger.error(
            "workflow_reminder unknown variant_selector=%s workflow=%s",
            selector,
            workflow_name,
        )
        return None
    return resolver(data)


def resolve_reminder_steps(
    reminders: WorkflowRemindersConfig,
    data: dict[str, Any],
    *,
    workflow_name: str,
) -> list[ReminderStepSpec] | None:
    try:
        if reminders.variants:
            key = _resolve_variant_key(reminders, data, workflow_name)
            if not key:
                return None
            return reminders.resolve_steps(variant_key=key)
        return reminders.resolve_steps()
    except KeyError:
        logger.error(
            "workflow_reminder variant not found workflow=%s key=%s",
            workflow_name,
            _resolve_variant_key(reminders, data, workflow_name),
        )
        return None


def build_enqueue_payload(
    data: dict[str, Any],
    *,
    workflow_name: str,
    reminders: WorkflowRemindersConfig,
) -> dict[str, Any]:
    keys = tuple(reminders.payload_keys) if reminders.payload_keys else _DEFAULT_PAYLOAD_KEYS
    out: dict[str, Any] = {
        "workflow_name": workflow_name,
        "tenant_slug": data.get("tenant_slug"),
    }
    for key in keys:
        if key in data and data.get(key) is not None:
            out[key] = data.get(key)
    thread = str(data.get("thread_id") or data.get("email_thread_id") or "").strip()
    if thread:
        out["thread_id"] = thread
    return out


def enrich_step_payload(
    base: dict[str, Any],
    *,
    step: ReminderStepSpec,
    reminders: WorkflowRemindersConfig,
    data: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(base)
    payload["event_type"] = step.event_type
    if step.step is not None:
        payload["reminder_step"] = int(step.step)

    templates = reminders.subject_templates
    if templates:
        step_key = str(step.step) if step.step is not None else "default"
        template = templates.get(step_key) or templates.get("default")
        if template:
            subject = template.format(offset_label=_reminder_offset_label(step.delay_hours))
            if step.step == 0:
                subject = (data.get("subject") or "").strip() or subject
            payload["subject"] = subject

    email_body = reminders.resolve_email_body()
    if email_body is not None:
        payload["body"] = (str(payload.get("body") or data.get("body") or "").strip()) or email_body

    return payload


def _parse_pickup_appointment_at(data: dict[str, Any]) -> datetime | None:
    raw = data.get("pickup_appointment_at")
    if raw is None or not str(raw).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _resolve_step_num(steps: list[ReminderStepSpec], step: ReminderStepSpec) -> int:
    for index, candidate in enumerate(steps, start=1):
        if (
            float(candidate.delay_hours) == float(step.delay_hours)
            and candidate.event_type == step.event_type
        ):
            return step.step if step.step is not None else index
    return step.step if step.step is not None else 1


class WorkflowReminderService:
    def _register_queued_tasks(
        self,
        data: dict[str, Any],
        *,
        queued: list[Any],
        steps: list[ReminderStepSpec],
    ) -> None:
        wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
        if not wl_id or not queued:
            return
        attempt = optional_routing_guide_attempt(data.get("routing_guide_attempt"))
        entries: list[dict[str, Any]] = []
        for result, step in zip(queued, steps, strict=False):
            task_id = getattr(result, "id", None)
            if not task_id:
                continue
            entry: dict[str, Any] = {
                "task_id": str(task_id),
                "event_type": step.event_type,
            }
            if attempt is not None:
                entry["attempt"] = attempt
            if step.step is not None:
                entry["step"] = int(step.step)
            entries.append(entry)
        if not entries:
            return
        cancel_service = WorkflowReminderCancelService()
        cancel_service.register_tasks(lifecycle_id=wl_id, entries=entries)

    def schedule(self, data: dict[str, Any], *, workflow_name: str) -> None:
        wf = (workflow_name or "").strip()
        if not wf:
            return

        if data.get("reminders_scheduled"):
            return

        reminders = parse_reminders_for_workflow(data, wf)
        if reminders is None:
            return

        trigger = (reminders.schedule_on_event_type or "").strip()
        if trigger and data.get("event_type") != trigger:
            return

        for key in _REQUIRED_SCHEDULE_KEYS:
            if not str(data.get(key) or "").strip():
                logger.warning(
                    "workflow_reminder missing %s workflow=%s",
                    key,
                    wf,
                )
                return

        wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
        skip_sub_statuses = _reminder_skip_sub_statuses(wf, reminders)
        if skip_sub_statuses:
            lifecycle_service = WorkflowLifecycleService()
            row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
            if not row:
                logger.warning(
                    "workflow_reminder lifecycle not found id=%s workflow=%s",
                    wl_id,
                    wf,
                )
                return
            current_sub = str(row.get("sub_status") or "").strip()
            if current_sub in skip_sub_statuses:
                data["reminders_scheduled"] = True
                return

        if reminders.schedule_mode == "before_pickup":
            self._schedule_before_pickup(data, workflow_name=wf, reminders=reminders)
            return

        steps = resolve_reminder_steps(reminders, data, workflow_name=wf)
        if not steps:
            return

        max_cd_hours = max(s.delay_hours for s in steps)
        expire_s = int(
            (
                timedelta(hours=max_cd_hours)
                + timedelta(hours=reminders.expire_grace_hours)
            ).total_seconds()
        )

        base_payload = build_enqueue_payload(data, workflow_name=wf, reminders=reminders)
        queued: list[Any] = []
        try:
            for step in steps:
                payload = enrich_step_payload(
                    base_payload, step=step, reminders=reminders, data=data
                )
                result = trigger_workflow_reminder.apply_async(
                    kwargs={"payload": payload},
                    countdown=timedelta(hours=step.delay_hours).total_seconds(),
                    expires=expire_s,
                )
                queued.append(result)
        except Exception:
            logger.exception(
                "workflow_reminder enqueue failed workflow=%s lifecycle_id=%s",
                wf,
                wl_id,
            )
            for item in queued:
                try:
                    item.revoke(terminate=False)
                except Exception:
                    pass
            return

        self._register_queued_tasks(data, queued=queued, steps=steps)
        data["reminders_scheduled"] = True

    def _schedule_before_pickup(
        self,
        data: dict[str, Any],
        *,
        workflow_name: str,
        reminders: WorkflowRemindersConfig,
    ) -> None:
        pickup_at = _parse_pickup_appointment_at(data)
        if pickup_at is None:
            logger.warning(
                "workflow_reminder missing pickup_appointment_at workflow=%s lifecycle_id=%s",
                workflow_name,
                data.get("workflow_lifecycle_id"),
            )
            return

        steps = reminders.resolve_steps()
        if not steps:
            return

        now = datetime.now(timezone.utc)
        plan = plan_before_pickup_reminders(
            pickup_at=pickup_at,
            now=now,
            steps=steps,
            min_gap_hours=float(reminders.min_gap_hours),
            catch_up_enabled=reminders.catch_up_missed_steps,
        )

        base_payload = build_enqueue_payload(
            data, workflow_name=workflow_name, reminders=reminders
        )
        tz = data.get("pickup_appointment_timezone")
        tz_str = str(tz).strip() if tz is not None and str(tz).strip() else None

        def _step_payload(step: ReminderStepSpec, step_num: int) -> dict[str, Any]:
            payload = enrich_step_payload(
                base_payload, step=step, reminders=reminders, data=data
            )
            if step.step is None:
                payload["reminder_step"] = step_num
            payload["pickup_appointment_at"] = pickup_at.isoformat()
            if tz_str:
                payload["pickup_appointment_timezone"] = tz_str
            return payload

        to_enqueue: list[tuple[datetime, dict[str, Any], ReminderStepSpec]] = []

        if plan.catch_up is not None:
            catch_num = _resolve_step_num(steps, plan.catch_up)
            to_enqueue.append(
                (now, _step_payload(plan.catch_up, catch_num), plan.catch_up)
            )

        for step, fire_at in plan.scheduled:
            step_num = _resolve_step_num(steps, step)
            to_enqueue.append((fire_at, _step_payload(step, step_num), step))

        reminder_steps = [
            {
                "step": _resolve_step_num(steps, step),
                "delay_hours": float(step.delay_hours),
                "fire_at": fire_at.isoformat(),
            }
            for step, fire_at in plan.scheduled
        ]

        if to_enqueue:
            latest_fire_at = max(fire_at for fire_at, _, _ in to_enqueue)
            expire_s = int(
                (
                    (latest_fire_at - now)
                    + timedelta(hours=reminders.expire_grace_hours)
                ).total_seconds()
            )
        else:
            expire_s = int(timedelta(hours=reminders.expire_grace_hours).total_seconds())

        queued: list[Any] = []
        enqueued_steps: list[ReminderStepSpec] = []
        try:
            for fire_at, payload, step in to_enqueue:
                result = trigger_workflow_reminder.apply_async(
                    kwargs={"payload": payload},
                    eta=fire_at,
                    expires=expire_s,
                )
                queued.append(result)
                enqueued_steps.append(step)
        except Exception:
            logger.exception(
                "workflow_reminder before_pickup enqueue failed workflow=%s lifecycle_id=%s",
                workflow_name,
                data.get("workflow_lifecycle_id"),
            )
            for item in queued:
                try:
                    item.revoke(terminate=False)
                except Exception:
                    pass
            return

        self._register_queued_tasks(data, queued=queued, steps=enqueued_steps)

        catch_up_info: dict[str, Any] | None = None
        if plan.catch_up is not None:
            catch_up_info = {
                "step": _resolve_step_num(steps, plan.catch_up),
                "delay_hours": float(plan.catch_up.delay_hours),
            }

        data["driver_reminder_schedule"] = {
            "pickup_appointment_at": pickup_at.isoformat(),
            "pickup_appointment_timezone": data.get("pickup_appointment_timezone"),
            "hours_remaining_at_schedule": plan.hours_remaining,
            "catch_up": catch_up_info,
            "reminder_steps": reminder_steps,
            "suppressed_steps": plan.suppressed,
            "skipped_steps": plan.skipped,
        }
        data["reminders_scheduled"] = True
