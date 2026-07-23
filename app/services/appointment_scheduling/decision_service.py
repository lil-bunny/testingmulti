"""Appointment scheduling LLM date decision (unified email path)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.models import LlmSchedulingDecision, PickupDropoffData
from app.domain.appointment_scheduling.scheduling_prompt_templates import (
    scheduling_optimization_prompt_variables,
)
from app.domain.prompt_step_keys import APPOINTMENT_SCHEDULING_OPTIMIZATION
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.ascend.availability import fetch_warehouse_availability
from app.integrations.langsmith import PromptTraceMetadata
from app.services.prompt_service import resolve_appointment_scheduling_optimization_prompts
from app.tools.appointment_scheduling.ascend_transforms import (
    llm_location_input_from_pickup_dropoff,
    normalize_availability_slots,
)
from app.tools.appointment_scheduling.scheduling_optimization import run_scheduling_optimization


class DecisionService:
    @staticmethod
    def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
        raw = tenant_settings.get("appointment_scheduling") or {}
        if isinstance(raw, T3raAppointmentSchedulingSettings):
            return raw
        return T3raAppointmentSchedulingSettings.model_validate(raw)

    def compute_decision(
        self,
        *,
        pickup_dropoff: PickupDropoffData,
        ascend_context: dict[str, Any],
        tenant_settings: dict[str, Any],
        customer_name: str,
    ) -> LlmSchedulingDecision:
        pickup_date = str((pickup_dropoff.pickup_data or {}).get("date") or "")

        office_code = str(ascend_context.get("office_code") or "")
        appointments = ascend_context.get("appointments") or []

        def _fetch_slots(loc_id_ref: str, iso_date: str, office: str):
            return fetch_warehouse_availability(
                loc_id_ref=loc_id_ref,
                date_iso=iso_date,
                office_code=office or office_code,
            )

        availability_result = normalize_availability_slots(
            appointments,
            pickup_date,
            office_code,
            fetch_slots=_fetch_slots,
        )
        location_input = llm_location_input_from_pickup_dropoff(
            pickup_dropoff.model_dump()
        )
        prompt_variables = scheduling_optimization_prompt_variables(
            location_input=location_input,
            availability=availability_result,
            customer_name=customer_name,
        )
        rendered, prompt_metadata = resolve_appointment_scheduling_optimization_prompts(
            tenant_settings,
            prompt_variables,
        )
        prompt_trace = PromptTraceMetadata.from_load(
            APPOINTMENT_SCHEDULING_OPTIMIZATION,
            prompt_metadata,
        )
        return run_scheduling_optimization(
            system_prompt=rendered.system,
            user_prompt=rendered.user,
            location_input=location_input,
            prompt_trace=prompt_trace,
        )
