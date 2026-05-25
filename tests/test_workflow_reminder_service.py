"""Tests for generic workflow reminder scheduling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.services.workflow_reminder_service import (
    WorkflowReminderService,
    build_enqueue_payload,
    enrich_step_payload,
    parse_reminders_for_workflow,
    resolve_reminder_steps,
)

_GELITA_FIXTURE = Path(__file__).resolve().parents[1] / "scripts" / "gelita_tenant_settings.json"
_T3RA_FIXTURE = Path(__file__).resolve().parents[1] / "scripts" / "t3ra_tenant_settings.json"


def _gelita_settings() -> dict:
    return json.loads(_GELITA_FIXTURE.read_text(encoding="utf-8"))


def _t3ra_settings() -> dict:
    return json.loads(_T3RA_FIXTURE.read_text(encoding="utf-8"))


def test_parse_gelita_reminders_from_fixture() -> None:
    data = {"tenant_settings": _gelita_settings()}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    assert cfg.schedule_on_event_type == "carrier_email_received"
    assert cfg.variant_selector == "load_type"


def test_ftl_steps_from_fixture() -> None:
    data = {
        "tenant_settings": _gelita_settings(),
        "load_type": "FTL",
    }
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) == 2
    assert steps[0].delay_hours == pytest.approx(0.166)
    assert steps[0].event_type == "reminder_due"
    assert steps[1].event_type == "escalation_due"


def test_ltl_steps_from_fixture() -> None:
    data = {"tenant_settings": _gelita_settings(), "load_type": "LTL"}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) == 3


def test_workflow_reminders_config_validates_fixture() -> None:
    raw = _gelita_settings()["load_tendering"]["reminders"]
    cfg = WorkflowRemindersConfig.model_validate(raw)
    assert cfg.variants is not None
    assert "ftl" in cfg.variants


def test_pod_payload_enrichment() -> None:
    raw = _t3ra_settings()["pod_lifecycle"]["reminders"]
    reminders = WorkflowRemindersConfig.model_validate(raw)
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
    assert "POD Reminder" in payload["subject"]
    assert payload["reminder_step"] == 1
    assert payload["body"] == "Please send pod"


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_load_tendering_enqueues(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    data = {
        "event_type": "carrier_email_received",
        "tenant_id": "tid",
        "tenant_slug": "gelita",
        "workflow_lifecycle_id": "wl-1",
        "thread_id": "th-1",
        "tender_id": "t-1",
        "load_type": "FTL",
        "tenant_settings": _gelita_settings(),
        "workflow_run_id": "run-1",
    }
    with patch(
        "app.services.workflow_reminder_service.WorkflowLifecycleService"
    ) as mock_lifecycle_cls:
        mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
            "sub_status": "tender_sent_to_carrier",
        }
        with patch(
            "app.services.workflow_reminder_service.LifecycleTransitionService"
        ):
            service = WorkflowReminderService()
            service.schedule(data, workflow_name="load_tendering")

    assert data["reminders_scheduled"] is True
    assert mock_task.apply_async.call_count == 2


def test_schedule_skips_wrong_event_type() -> None:
    data = {
        "event_type": "route_completed",
        "tenant_id": "tid",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _gelita_settings(),
    }
    service = WorkflowReminderService()
    with patch("app.services.workflow_reminder_service.trigger_workflow_reminder") as mock_task:
        service.schedule(data, workflow_name="load_tendering")
        mock_task.apply_async.assert_not_called()


def test_schedule_skips_when_already_scheduled() -> None:
    data = {
        "reminders_scheduled": True,
        "event_type": "carrier_email_received",
        "tenant_settings": _gelita_settings(),
    }
    service = WorkflowReminderService()
    with patch("app.services.workflow_reminder_service.trigger_workflow_reminder") as mock_task:
        service.schedule(data, workflow_name="load_tendering")
        mock_task.apply_async.assert_not_called()
