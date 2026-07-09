"""Tests for generic workflow reminder scheduling.

Gelita / t3ra ``tenant_settings`` are read from ``tenants.settings`` in Postgres
(see ``scripts/tenant_settings/<slug>/*.tenant_settings.dev.json`` for local dev fixtures).
When ``DATABASE_URL`` is unset or the slug has no reminders block, DB-backed tests skip.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.repositories.tenants_db_repository import fetch_tenant_settings_by_slug
from app.services.workflow_reminder_service import (
    WorkflowReminderService,
    build_enqueue_payload,
    enrich_step_payload,
    parse_reminders_for_workflow,
    resolve_reminder_steps,
)

# Minimal config for schedule routing tests (no DB).
_MINIMAL_LOAD_TENDERING_REMINDERS: dict[str, Any] = {
    "load_tendering": {
        "reminders": {
            "variants": {
                "ftl": [
                    {"step": 1, "event_type": "reminder_due", "delay_hours": 1.0},
                    {"event_type": "escalation_due", "delay_hours": 2.0},
                ],
            },
            "variant_selector": "load_type",
            "expire_grace_hours": 2,
            "schedule_on_event_type": "carrier_email_received",
        },
    },
}


def _require_tenant_settings(slug: str) -> dict[str, Any]:
    if not (settings.DATABASE_URL or "").strip():
        pytest.skip("DATABASE_URL not set — load tenant settings from Postgres for this test")
    try:
        raw = fetch_tenant_settings_by_slug(slug)
    except Exception as exc:
        pytest.skip(f"tenants DB unavailable: {exc}")
    if not raw:
        pytest.skip(f"no tenants.settings row for slug={slug!r}")
    return raw


def _gelita_settings() -> dict[str, Any]:
    return _require_tenant_settings("gelita")


def _t3ra_settings() -> dict[str, Any]:
    return _require_tenant_settings("t3ra")


def test_parse_gelita_reminders_from_db() -> None:
    data = {"tenant_settings": _gelita_settings()}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    assert cfg.schedule_on_event_type == "carrier_email_received"
    assert cfg.variant_selector == "load_type"


def test_ftl_steps_from_db() -> None:
    data = {
        "tenant_settings": _gelita_settings(),
        "load_type": "FTL",
    }
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) >= 1
    assert steps[0].event_type == "reminder_due"
    assert steps[0].delay_hours > 0


def test_ltl_steps_from_db() -> None:
    data = {"tenant_settings": _gelita_settings(), "load_type": "LTL"}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) >= 2


def test_workflow_reminders_config_validates_gelita_db_block() -> None:
    raw = _gelita_settings()["load_tendering"]["reminders"]
    cfg = WorkflowRemindersConfig.model_validate(raw)
    assert cfg.variants is not None
    assert "ftl" in cfg.variants


def test_pod_payload_enrichment_from_db() -> None:
    raw = _t3ra_settings()["pod_lifecycle"]["reminders"]
    reminders = WorkflowRemindersConfig.model_validate(raw)
    assert reminders.steps is not None
    assert len(reminders.steps) >= 2
    step = reminders.steps[1]
    base = build_enqueue_payload(
        {"tenant_slug": "t3ra", "tenant_id": "t1"},
        workflow_name="pod_lifecycle",
        reminders=reminders,
    )
    payload = enrich_step_payload(
        base,
        step=step,
        reminders=reminders,
        data={"subject": "Original"},
    )
    assert payload["reminder_step"] == step.step
    assert payload["schedule_reminder_step"] == step.step
    assert payload.get("body") or reminders.default_body


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_load_tendering_enqueues(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    gelita = _gelita_settings()
    data = {
        "event_type": "carrier_email_received",
        "tenant_id": "tid",
        "tenant_slug": "gelita",
        "workflow_lifecycle_id": "wl-1",
        "thread_id": "th-1",
        "tender_id": "t-1",
        "load_type": "FTL",
        "tenant_settings": gelita,
        "workflow_run_id": "run-1",
    }
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    expected_count = len(steps)

    with patch(
        "app.services.workflow_reminder_service.WorkflowLifecycleService"
    ) as mock_lifecycle_cls:
        mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
            "sub_status": "tender_sent_to_carrier",
        }
        service = WorkflowReminderService()
        service.schedule(data, workflow_name="load_tendering")

    assert data["reminders_scheduled"] is True
    assert mock_task.apply_async.call_count == expected_count


def test_schedule_skips_wrong_event_type() -> None:
    data = {
        "event_type": "route_completed",
        "tenant_id": "tid",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _MINIMAL_LOAD_TENDERING_REMINDERS,
    }
    service = WorkflowReminderService()
    with patch("app.services.workflow_reminder_service.trigger_workflow_reminder") as mock_task:
        service.schedule(data, workflow_name="load_tendering")
        mock_task.apply_async.assert_not_called()


def test_schedule_skips_when_already_scheduled() -> None:
    data = {
        "reminders_scheduled": True,
        "event_type": "carrier_email_received",
        "tenant_settings": _MINIMAL_LOAD_TENDERING_REMINDERS,
    }
    service = WorkflowReminderService()
    with patch("app.services.workflow_reminder_service.trigger_workflow_reminder") as mock_task:
        service.schedule(data, workflow_name="load_tendering")
        mock_task.apply_async.assert_not_called()
