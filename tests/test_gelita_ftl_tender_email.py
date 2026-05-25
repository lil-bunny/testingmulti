"""Tests for FTL tender email builder and reminder schedule specs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.load_tendering_settings import (
    action_settings,
    is_ftl_load_type,
    load_type_bucket,
)
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.services.workflow_reminder_service import (
    parse_reminders_for_workflow,
    resolve_reminder_steps,
)
from app.workflows.nodes.gelita.load_tendering_helpers import build_gelita_ftl_tender_email

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gelita_tenant_settings.json"


def _tenant_settings() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_is_ftl_load_type_and_bucket() -> None:
    assert is_ftl_load_type("FTL")
    assert is_ftl_load_type("ftl")
    assert not is_ftl_load_type("LTL")
    assert load_type_bucket("FTL") == "ftl"
    assert load_type_bucket("LTL") == "ltl"


def test_build_gelita_ftl_tender_email_placeholders() -> None:
    template = action_settings(
        {"tenant_settings": _tenant_settings()},
        "send_tender_email",
        load_type="FTL",
    )["email_template_html"]
    built = build_gelita_ftl_tender_email(
        {
            "order_number": "ORD-1",
            "customer_po": "PO-9",
            "ship_date": "2026-05-01",
            "delivery_date": "2026-05-10",
            "order_value": "12000",
            "delivery_address": "Now Foods\n123 Main St\nReno NV 89501",
        },
        {"pallets_count": "12.00"},
        template,
    )
    assert built["subject"] == "Load tender — Order ORD-1"
    assert "ORD-1" in built["body_html"]
    assert "PO-9" in built["body_html"]
    assert "2026-05-10" in built["body_html"]
    assert "12.00" in built["body_html"]
    assert "opendock.com" in built["body_html"]
    assert "<!DOCTYPE html>" in template


def test_ftl_reminder_schedule_specs() -> None:
    data = {"tenant_settings": _tenant_settings(), "load_type": "FTL"}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) == 2
    assert steps[0].delay_hours == pytest.approx(0.166)
    assert steps[0].event_type == "reminder_due"
    assert steps[0].step == 1
    assert steps[1].event_type == "escalation_due"


def test_ltl_reminder_schedule_specs() -> None:
    data = {"tenant_settings": _tenant_settings(), "load_type": "LTL"}
    cfg = parse_reminders_for_workflow(data, "load_tendering")
    assert cfg is not None
    steps = resolve_reminder_steps(cfg, data, workflow_name="load_tendering")
    assert steps is not None
    assert len(steps) == 3
    assert steps[0].delay_hours == pytest.approx(0.166)
    assert steps[1].delay_hours == pytest.approx(0.333)
    assert steps[2].delay_hours == pytest.approx(0.1)


def test_ltl_and_ftl_escalation_bodies_differ() -> None:
    state = SimpleNamespace(data={"tenant_settings": _tenant_settings()})
    ltl = action_settings(state, "escalate_tender", load_type="LTL")
    ftl = action_settings(state, "escalate_tender", load_type="FTL")
    assert "LTL tender escalation" in ltl["escalation_email_body"]
    assert "FTL tender escalation" in ftl["escalation_email_body"]
    assert "<!DOCTYPE html>" in ltl["escalation_email_body"]
    assert "<!DOCTYPE html>" in ftl["escalation_email_body"]


def test_reminder_bodies_are_html() -> None:
    state = SimpleNamespace(data={"tenant_settings": _tenant_settings()})
    ltl = action_settings(state, "send_tender_reminder", load_type="LTL")
    ftl = action_settings(state, "send_tender_reminder", load_type="FTL")
    assert "<!DOCTYPE html>" in ltl["reminder_body"]
    assert "<!DOCTYPE html>" in ftl["reminder_body"]
