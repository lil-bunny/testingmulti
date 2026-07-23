"""Appointment scheduling intake orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.models import CustomerContactRow, DraftStatic, PickupDropoffData
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.appointment_scheduling.skip_reasons import scheduling_failure_from_skip
from app.domain.error_catalog import IntegrationError, SystemError
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.ascend.appointments import get_loc_ref_for_ascend_slots
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError
from app.integrations.ascend.error_mapping import catalog_from_ascend_api_error
from app.integrations.ascend.shipments import fetched_shipment_details
from app.integrations.google.sheets import GoogleSheetsError
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    delivery_stop_name_from_payload,
    get_shipment as get_shipment_async,
)
from app.services.appointment_scheduling.recipient_contact_gate import (
    contact_from_rows_skip_reason,
)
from app.services.appointment_scheduling.sheet_loader import load_appointment_sheet_rows
from app.tools.appointment_scheduling.ascend_transforms import pickup_dropoff_from_ascend_shipment
from app.tools.appointment_scheduling.customer_contact import customer_contact_from_rows
from app.tools.appointment_scheduling.draft_email import (
    build_draft_static_from_turvo,
    build_shipment_details_summary,
)
from app.services.appointment_scheduling.ascend_settings import (
    load_appointment_scheduling_settings,
)
from app.tools.appointment_scheduling.ingress import (
    customer_id_from_turvo_shipment,
    reference_number_from_turvo_shipment,
)


@dataclass(frozen=True)
class IntakeResult:
    ok: bool
    failure: SchedulingFailure | None = None
    shipment: dict[str, Any] | None = None
    ascend_shipment: dict[str, Any] | None = None
    customer_contact: CustomerContactRow | None = None
    pickup_dropoff_data: PickupDropoffData | None = None
    draft_static: DraftStatic | None = None
    customer_name: str | None = None
    customer_id: str | None = None
    reference_number: str | None = None
    office_code: str | None = None
    ascend_appointments: list[dict[str, Any]] | None = None


class AppointmentSchedulingIntakeService:
    @staticmethod
    def _turvo_shipment_from_payload(
        payload: dict[str, Any],
        *,
        tenant_slug: str,
        shipment_id: str,
    ) -> dict[str, Any]:
        cached = payload.get("shipment")
        if isinstance(cached, dict):
            return cached
        return run_sync(get_shipment_async(tenant_slug, shipment_id))

    @staticmethod
    def _contact_from_payload(
        payload: dict[str, Any],
        *,
        tenant_settings: dict[str, Any],
        turvo_shipment: dict[str, Any],
        sheet_customer: str,
    ) -> tuple[CustomerContactRow | None, IntakeResult | None]:
        raw_contact = payload.get("customer_contact")
        if isinstance(raw_contact, CustomerContactRow):
            return raw_contact, None
        if isinstance(raw_contact, dict) and str(raw_contact.get("email") or "").strip():
            return CustomerContactRow.model_validate(raw_contact), None

        settings = AppointmentSchedulingIntakeService._settings(tenant_settings)
        sheet_source = str(settings.appointment_data_source or "").strip()
        if not sheet_source:
            return None, AppointmentSchedulingIntakeService._failure(
                "missing_appointment_data_source",
                customer_name=sheet_customer,
            )
        try:
            rows = load_appointment_sheet_rows(sheet_source)
        except (OSError, GoogleSheetsError, ValueError):
            return None, AppointmentSchedulingIntakeService._failure(
                "appointment_sheet_unreadable",
                customer_name=sheet_customer,
            )
        if skip := contact_from_rows_skip_reason(rows, sheet_customer):
            return None, AppointmentSchedulingIntakeService._failure(
                skip,
                customer_name=sheet_customer,
            )
        return customer_contact_from_rows(rows, sheet_customer), None

    @staticmethod
    def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
        raw = tenant_settings.get("appointment_scheduling") or {}
        if isinstance(raw, T3raAppointmentSchedulingSettings):
            return raw
        return T3raAppointmentSchedulingSettings.model_validate(raw)

    @staticmethod
    def _failure(
        skip_reason: str,
        *,
        customer_name: str = "",
        reference_number: str = "",
    ) -> IntakeResult:
        failure = scheduling_failure_from_skip(
            skip_reason,
            customer_name=customer_name,
            reference_number=reference_number,
        )
        if failure is None:
            failure = SchedulingFailure(
                code=skip_reason,
                message=skip_reason.replace("_", " "),
                category=SystemError.UNEXPECTED_NODE_FAILURE.category,
            )
        return IntakeResult(ok=False, failure=failure)

    def run_intake(
        self,
        *,
        tenant_slug: str,
        tenant_settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> IntakeResult:
        shipment_id = str(payload.get("shipment_id") or "").strip()
        if not shipment_id:
            return self._failure("missing_shipment_id")

        try:
            turvo_shipment = self._turvo_shipment_from_payload(
                payload,
                tenant_slug=tenant_slug,
                shipment_id=shipment_id,
            )
        except TurvoApiError as exc:
            return IntakeResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
                    str(exc),
                ),
            )
        reference_number = (
            str(payload.get("reference_number") or "").strip()
            or reference_number_from_turvo_shipment(turvo_shipment)
            or ""
        )
        sheet_customer = (
            str(payload.get("customer_name") or "").strip()
            or delivery_stop_name_from_payload(turvo_shipment)
            or ""
        )
        customer_id = customer_id_from_turvo_shipment(turvo_shipment) or ""

        contact, contact_failure = self._contact_from_payload(
            payload,
            tenant_settings=tenant_settings,
            turvo_shipment=turvo_shipment,
            sheet_customer=sheet_customer,
        )
        if contact_failure is not None:
            return contact_failure
        if contact is None:
            return self._failure("missing_recipient_email", customer_name=sheet_customer)

        office_code = ascend_office_code_from_reference(reference_number=reference_number)
        ascend_settings = load_appointment_scheduling_settings(tenant_slug)
        if not ascend_settings.ascend_email or not ascend_settings.ascend_password:
            return self._failure("ascend_not_configured", customer_name=sheet_customer)

        try:
            auth = login_ascend_api(
                email=ascend_settings.ascend_email,
                password=ascend_settings.ascend_password,
            )
            access_token = str(auth.get("accessToken") or "")
        except AscendApiError as exc:
            catalog, message = catalog_from_ascend_api_error(exc, operation="login")
            return IntakeResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(catalog, message),
            )

        try:
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
        except AscendApiError as exc:
            catalog, message = catalog_from_ascend_api_error(
                exc,
                operation="shipment_fetch",
                reference_number=reference_number,
            )
            return IntakeResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(catalog, message),
            )

        pickup_raw = pickup_dropoff_from_ascend_shipment(ascend_shipment)
        if pickup_raw.get("error"):
            return self._failure(
                "pickup_dropoff_extract_failed",
                reference_number=reference_number,
            )

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
            customer_name=sheet_customer,
            customer_id=customer_id,
            reference_number=reference_number,
            office_code=office_code,
            ascend_appointments=appointments,
        )
