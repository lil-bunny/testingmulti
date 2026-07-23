"""Appointment scheduling decision service tests."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.appointment_scheduling.models import LlmSchedulingDecision, PickupDropoffData
from app.domain.prompt_step_keys import APPOINTMENT_SCHEDULING_OPTIMIZATION
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.appointment_scheduling.decision_service import (
    DecisionService,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def test_compute_decision_uses_langsmith_prompt_and_trace():
    service = DecisionService()
    tenant_settings = minimal_t3ra_tenant_settings()
    pickup = PickupDropoffData(
        pickup_data={"date": "07/01/2026", "time": "10:00", "location": "Ripon", "state_name": "CA"},
        dropoff_data={"location": "Aurora", "state_name": "OR"},
        miles=500,
    )
    rendered = RenderedPrompt(system="system rules", user="user payload")
    metadata = PromptLoadMetadata(source="fallback", tenant_prompt_ref="inline")

    with patch(
        "app.services.appointment_scheduling.decision_service.normalize_availability_slots",
        return_value={"availability": {"07/01/2026": {"times": ["15:00"], "pcs_format": "07/01/2026"}}},
    ), patch(
        "app.services.appointment_scheduling.decision_service.resolve_appointment_scheduling_optimization_prompts",
        return_value=(rendered, metadata),
    ) as mock_resolve, patch(
        "app.services.appointment_scheduling.decision_service.run_scheduling_optimization",
        return_value=LlmSchedulingDecision(
            calculated_delivery_date="07/04/2026",
            calculated_delivery_weekday="SATURDAY",
        ),
    ) as mock_llm:
        result = service.compute_decision(
            pickup_dropoff=pickup,
            ascend_context={"office_code": "DIAMOND-RPN", "appointments": [{"warehouse": "WH-1"}]},
            tenant_settings=tenant_settings,
            customer_name="WINCO FOODS",
        )

    assert result.calculated_delivery_date == "07/04/2026"
    mock_resolve.assert_called_once()
    mock_llm.assert_called_once()
    kwargs = mock_llm.call_args.kwargs
    assert kwargs["system_prompt"] == "system rules"
    assert kwargs["user_prompt"] == "user payload"
    assert kwargs["prompt_trace"].prompt_step_key == APPOINTMENT_SCHEDULING_OPTIMIZATION


def test_compute_decision_uses_llm_for_costco():
    """Costco takes the same LLM + availability path as every other email customer."""
    service = DecisionService()
    pickup = PickupDropoffData(
        pickup_data={"date": "07/01/2026", "time": "10:00", "location": "Ripon", "state_name": "CA"},
        dropoff_data={"location": "Aurora", "state_name": "OR"},
        miles=500,
    )
    rendered = RenderedPrompt(system="system rules", user="user payload")
    metadata = PromptLoadMetadata(source="fallback", tenant_prompt_ref="inline")

    with patch(
        "app.services.appointment_scheduling.decision_service.normalize_availability_slots",
        return_value={"availability": {"07/01/2026": {"times": ["15:00"], "pcs_format": "07/01/2026"}}},
    ) as mock_avail, patch(
        "app.services.appointment_scheduling.decision_service.resolve_appointment_scheduling_optimization_prompts",
        return_value=(rendered, metadata),
    ), patch(
        "app.services.appointment_scheduling.decision_service.run_scheduling_optimization",
        return_value=LlmSchedulingDecision(
            calculated_delivery_date="07/03/2026",
            calculated_delivery_weekday="FRIDAY",
        ),
    ) as mock_llm:
        result = service.compute_decision(
            pickup_dropoff=pickup,
            ascend_context={"office_code": "DIAMOND-RPN", "appointments": [{"warehouse": "WH-1"}]},
            tenant_settings=minimal_t3ra_tenant_settings(),
            customer_name="Costco Wholesale",
        )

    mock_avail.assert_called_once()
    mock_llm.assert_called_once()
    assert result.calculated_delivery_date == "07/03/2026"
