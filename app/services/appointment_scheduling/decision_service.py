"""Appointment scheduling LLM / simplified date decision."""

from __future__ import annotations

from datetime import datetime, timedelta
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
from app.domain.appointment_scheduling.costco import is_costco_customer
from app.tools.appointment_scheduling.scheduling_optimization import run_scheduling_optimization


class AppointmentSchedulingDecisionService:
    @staticmethod
    def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
        raw = tenant_settings.get("appointment_scheduling") or {}
        if isinstance(raw, T3raAppointmentSchedulingSettings):
            return raw
        return T3raAppointmentSchedulingSettings.model_validate(raw)

    @staticmethod
    def _parse_transit_days(transit_time: str, default: int = 3) -> int:
        text = str(transit_time or "").strip().lower()
        for token in text.replace("days", "").replace("day", "").split():
            try:
                return max(1, int(float(token)))
            except ValueError:
                continue
        return default

    @staticmethod
    def _add_business_days(start_mm_dd_yyyy: str, days: int) -> tuple[str, str]:
        try:
            current = datetime.strptime(start_mm_dd_yyyy.strip(), "%m/%d/%Y").date()
        except ValueError:
            return start_mm_dd_yyyy, "DAY"
        added = 0
        while added < days:
            current += timedelta(days=1)
            if current.weekday() >= 5:
                continue
            added += 1
        delivery = current.strftime("%m/%d/%Y")
        return delivery, current.strftime("%A").upper()

    def compute_decision(
        self,
        *,
        pickup_dropoff: PickupDropoffData,
        ascend_context: dict[str, Any],
        tenant_settings: dict[str, Any],
        customer_name: str,
        customer_contact_transit_time: str = "",
    ) -> LlmSchedulingDecision:
        pickup_date = str((pickup_dropoff.pickup_data or {}).get("date") or "")

        if is_costco_customer(customer_name):
            transit_days = self._parse_transit_days(customer_contact_transit_time)
            delivery_date, weekday = self._add_business_days(pickup_date, transit_days)
            return LlmSchedulingDecision(
                calculated_delivery_date=delivery_date,
                calculated_delivery_weekday=weekday,
                selected_pickup_date=pickup_date,
                pcs_pickup_date=pickup_date,
                transit_days=transit_days,
            )

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
