"""Build appointment scheduling email draft for lifecycle metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.appointment_scheduling.models import (
    DraftStatic,
    EmailDraft,
    LlmSchedulingDecision,
    PickupDropoffData,
    SchedulingPayload,
)
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.tools.appointment_scheduling.draft_email import build_email_draft


@dataclass(frozen=True)
class EmailDraftResult:
    email_draft: dict[str, Any]
    scheduling_payload: dict[str, Any]


class AppointmentSchedulingDraftService:
    @staticmethod
    def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
        raw = tenant_settings.get("appointment_scheduling") or {}
        if isinstance(raw, T3raAppointmentSchedulingSettings):
            return raw
        return T3raAppointmentSchedulingSettings.model_validate(raw)

    @staticmethod
    def _parse_cc(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [part.strip() for part in text.split(",") if part.strip()]

    def build_email_draft(
        self,
        *,
        pickup_dropoff: PickupDropoffData,
        llm_decision: LlmSchedulingDecision,
        draft_static: DraftStatic,
        to_email: str,
        tenant_settings: dict[str, Any],
        load_id: str,
        customer_name: str,
    ) -> EmailDraftResult:
        settings = self._settings(tenant_settings)
        email_draft, scheduling_payload = build_email_draft(
            pickup_dropoff=pickup_dropoff,
            llm_decision=llm_decision,
            draft_static=draft_static,
            to_email=to_email,
            cc=self._parse_cc(settings.email_cc),
            load_id=load_id,
            customer_name=customer_name,
        )
        return EmailDraftResult(
            email_draft=email_draft.model_dump(mode="json"),
            scheduling_payload=scheduling_payload.model_dump(mode="json"),
        )
