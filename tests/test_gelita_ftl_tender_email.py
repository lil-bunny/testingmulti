"""Tests for FTL tender email builder and reminder schedule specs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.domain.load_tendering_settings import (
    action_settings,
    is_ftl_load_type,
    load_type_bucket,
)
from app.services.gelita_reminder_scheduler import _reminder_schedule_specs
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
    data = {"tenant_settings": _tenant_settings()}
    specs = _reminder_schedule_specs(data, "FTL")
    assert len(specs) == 2
    assert specs[0] == (24.0, "reminder_due", 1)
    assert specs[1] == (28.0, "escalation_due", None)


def test_ltl_reminder_schedule_specs() -> None:
    data = {"tenant_settings": _tenant_settings()}
    specs = _reminder_schedule_specs(data, "LTL")
    assert len(specs) == 3
    assert specs[0][0] == 12.0
    assert specs[1][0] == 24.0
    assert specs[2][0] == 0.1


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
