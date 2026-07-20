"""Scheduling optimization prompt template tests."""

from __future__ import annotations

from pathlib import Path

from langchain_core.load.load import loads

from app.domain.appointment_scheduling.scheduling_prompt_templates import (
    format_availability_text,
    render_inline_scheduling_optimization_prompts,
    scheduling_optimization_prompt_variables,
)
from app.integrations.langsmith.render import render_system_user
from app.services.prompt_service import resolve_appointment_scheduling_optimization_prompts


def test_scheduling_prompt_variables_include_availability_text():
    variables = scheduling_optimization_prompt_variables(
        location_input={
            "pickup_location": "Ripon",
            "dropoff_location": "Aurora",
            "pickup_state": "CA",
            "dropoff_state": "OR",
            "startDateInput": "07/01/2026",
            "startTimeInput": "10:00",
            "miles": 500,
        },
        availability={
            "availability": {
                "07/01/2026": {"pcs_format": "07/01/2026", "times": ["15:00", "16:00"]},
            }
        },
        customer_name="WINCO FOODS",
    )
    assert "Ripon" in variables["pickup_location"]
    assert "15:00" in variables["availability_text"]
    assert variables["customer_name"] == "WINCO FOODS"


def test_inline_prompt_render_includes_shipment_context():
    variables = scheduling_optimization_prompt_variables(
        location_input={"miles": 100, "startDateInput": "07/01/2026", "startTimeInput": "09:00"},
        availability={"availability": {}},
        customer_name="CHEWY",
    )
    system, user = render_inline_scheduling_optimization_prompts(variables)
    assert "CHEWY" in system
    assert "Structured input" in user


def test_fallback_prompt_template_loads_and_renders():
    path = Path("prompts/fallbacks/scheduling-optimization.json")
    template = loads(path.read_text(encoding="utf-8"))
    variables = scheduling_optimization_prompt_variables(
        location_input={"miles": 250, "startDateInput": "07/02/2026", "startTimeInput": "11:00"},
        availability={"availability": {"07/02/2026": {"times": ["17:00"], "pcs_format": "07/02/2026"}}},
        customer_name="AFCO",
    )
    rendered = render_system_user(template, variables)
    assert rendered.system
    assert rendered.user
    assert "250" in rendered.system


def test_resolve_uses_tenant_prompt_ref_without_hub():
    tenant_settings = {
        "prompts": {
            "appointment_scheduling": {
                "scheduling_optimization": "scheduling-optimization:staging",
            }
        }
    }
    variables = scheduling_optimization_prompt_variables(
        location_input={"miles": 10, "startDateInput": "07/01/2026", "startTimeInput": "08:00"},
        availability={"availability": {}},
        customer_name="Test",
    )
    rendered, metadata = resolve_appointment_scheduling_optimization_prompts(
        tenant_settings,
        variables,
    )
    assert rendered.system
    assert rendered.user
    assert metadata.tenant_prompt_ref == "scheduling-optimization:staging"


def test_format_availability_text_empty():
    assert format_availability_text({}) == "(no availability slots)"
