"""Appointment scheduling intake orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.domain.appointment_scheduling.models import CustomerContactRow, DraftStatic, PickupDropoffData
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.ascend.appointments import get_loc_ref_for_ascend_slots
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError
from app.integrations.ascend.shipments import fetched_shipment_details
from app.integrations.google.sheets import GoogleSheetsError
from app.integrations.turvo.shipments import get_shipment as get_shipment_async
from app.services.appointment_scheduling.sheet_loader import load_appointment_sheet_rows
from app.tools.appointment_scheduling.ascend_transforms import pickup_dropoff_from_ascend_shipment
from app.tools.appointment_scheduling.customer_contact import customer_contact_from_rows
from app.tools.appointment_scheduling.draft_email import (
    build_draft_static_from_turvo,
    build_shipment_details_summary,
)
from app.tools.appointment_scheduling.ingress import (
    customer_id_from_turvo_shipment,
    customer_name_from_turvo_shipment,
    reference_number_from_turvo_shipment,
)


@dataclass(frozen=True)
class IntakeResult:
    ok: bool
    skip_reason: str | None = None
    shipment: dict[str, Any] | None = None
    ascend_shipment: dict[str, Any] | None = None
    customer_contact: CustomerContactRow | None = None
    pickup_dropoff_data: PickupDropoffData | None = None
    draft_static: DraftStatic | None = None
    customer_name: str | None = None
    customer_id: str | None = None
    reference_number: str | None = None
    office_code: str | None = None
    ascend_access_token: str | None = None
    ascend_appointments: list[dict[str, Any]] | None = None


class AppointmentSchedulingIntakeService:
    @staticmethod
    def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
        raw = tenant_settings.get("appointment_scheduling") or {}
        if isinstance(raw, T3raAppointmentSchedulingSettings):
            return raw
        return T3raAppointmentSchedulingSettings.model_validate(raw)

    def run_intake(
        self,
        *,
        tenant_slug: str,
        tenant_settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> IntakeResult:
        settings = self._settings(tenant_settings)
        shipment_id = str(payload.get("shipment_id") or "").strip()
        if not shipment_id:
            return IntakeResult(ok=False, skip_reason="missing_shipment_id")

        turvo_shipment = asyncio.run(get_shipment_async(tenant_slug, shipment_id))
        reference_number = (
            str(payload.get("reference_number") or "").strip()
            or reference_number_from_turvo_shipment(turvo_shipment)
            or ""
        )
        customer_name = customer_name_from_turvo_shipment(turvo_shipment) or ""
        customer_id = customer_id_from_turvo_shipment(turvo_shipment) or ""

        sheet_source = str(settings.appointment_data_source or "").strip()
        if not sheet_source:
            return IntakeResult(ok=False, skip_reason="missing_appointment_data_source")
        try:
            rows = load_appointment_sheet_rows(sheet_source)
        except (OSError, GoogleSheetsError, ValueError):
            return IntakeResult(ok=False, skip_reason="appointment_sheet_unreadable")

        contact = customer_contact_from_rows(rows, customer_name)
        if contact is None or not contact.email:
            return IntakeResult(ok=False, skip_reason="missing_recipient_email")

        office_code = ascend_office_code_from_reference(reference_number=reference_number)
        if not settings.ascend_email or not settings.ascend_password:
            return IntakeResult(ok=False, skip_reason="ascend_not_configured")
        try:
            auth = login_ascend_api(
                email=settings.ascend_email,
                password=settings.ascend_password,
            )
            access_token = str(auth.get("accessToken") or "")
            ascend_shipment = fetched_shipment_details(
                reference_number=reference_number,
                access_token=access_token,
                office_code=office_code,
            )
            appointments = get_loc_ref_for_ascend_slots(
                reference_number=reference_number,
                access_token=access_token,
                office_code=office_code,
            )
        except AscendApiError:
            return IntakeResult(ok=False, skip_reason="ascend_fetch_failed")

        pickup_raw = pickup_dropoff_from_ascend_shipment(ascend_shipment)
        if pickup_raw.get("error"):
            return IntakeResult(ok=False, skip_reason="pickup_dropoff_extract_failed")

        pickup_dropoff = PickupDropoffData.model_validate(pickup_raw)
        shipment_details = build_shipment_details_summary(
            reference_number=reference_number,
            pickup_dropoff=pickup_raw,
        )
        mikey = tenant_settings.get("mikey_account_id") or {}
        footer_email = ""
        if isinstance(mikey, dict):
            footer_email = str(mikey.get("email_alias") or "").strip()
        draft_static = build_draft_static_from_turvo(
            turvo_shipment=turvo_shipment,
            reference_number=reference_number,
            shipment_details=shipment_details,
            footer_email=footer_email or "mikey@t3ralogistics.com",
        )

        return IntakeResult(
            ok=True,
            shipment=turvo_shipment,
            ascend_shipment=ascend_shipment,
            customer_contact=contact,
            pickup_dropoff_data=pickup_dropoff,
            draft_static=draft_static,
            customer_name=customer_name,
            customer_id=customer_id,
            reference_number=reference_number,
            office_code=office_code,
            ascend_access_token=access_token,
            ascend_appointments=appointments,
        )
