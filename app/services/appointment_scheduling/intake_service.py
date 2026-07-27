"""Appointment scheduling intake orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.models import (
    CustomerContactRow,
    DraftStatic,
    LlmAppointmentDecision,
    PickupDropoffData,
)
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.error_catalog import BusinessError, ErrorCode, IntegrationError
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.ascend.appointments import get_loc_ref_for_ascend_slots
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError, AscendError, is_ascend_timeout
from app.integrations.ascend.shipments import fetched_shipment_details
from app.integrations.google.sheets import GoogleSheetsError
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    delivery_stop_name_from_payload,
    get_shipment as get_shipment_async,
)
from app.services.appointment_scheduling.sheet_loader import load_appointment_customer_rows
from app.tools.appointment_scheduling.ascend_transforms import pickup_dropoff_from_ascend_shipment
from app.tools.appointment_scheduling.customer_contact import (
    appointment_mode_from_row,
    customer_contact_from_row,
    customer_contact_from_rows,
    find_customer_sheet_row,
    is_email_appointment_mode,
)
from app.tools.appointment_scheduling.draft_email import (
    build_draft_static_from_turvo,
    build_email_draft,
    build_shipment_details_summary,
)
from app.domain.appointment_scheduling.settings import load_appointment_scheduling_settings
from app.services.shipment_location_link_service import ShipmentLocationLinkService
from app.tools.appointment_scheduling.ingress import reference_number_from_turvo_shipment


@dataclass(frozen=True)
class EmailDraftResult:
    email_draft: dict[str, Any]
    appointment_payload: dict[str, Any]


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
    reference_number: str | None = None
    office_code: str | None = None
    ascend_appointments: list[dict[str, Any]] | None = None


class IntakeService:
    def __init__(
        self,
        *,
        location_link_service: ShipmentLocationLinkService | None = None,
    ) -> None:
        self._location_link = location_link_service or ShipmentLocationLinkService()

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

        settings = IntakeService._settings(tenant_settings)
        sheet_source = str(settings.appointment_data_source or "").strip()
        if not sheet_source:
            return None, IntakeService._failure(
                BusinessError.MISSING_APPOINTMENT_DATA_SOURCE,
                customer_name=sheet_customer,
            )
        try:
            rows = load_appointment_customer_rows(sheet_source, sheet_customer)
        except (OSError, GoogleSheetsError, ValueError):
            return None, IntakeService._failure(
                BusinessError.APPOINTMENT_SHEET_UNREADABLE,
                customer_name=sheet_customer,
            )
        if skip := contact_from_rows_skip_reason(rows, sheet_customer):
            return None, IntakeService._failure(
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
        error: ErrorCode,
        **context: str,
    ) -> IntakeResult:
        return IntakeResult(
            ok=False,
            failure=SchedulingFailure.from_catalog(error, **context),
        )

    def run_intake(
        self,
        *,
        tenant_slug: str,
        tenant_settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> IntakeResult:
        shipment_id = str(payload.get("shipment_id") or "").strip()
        if not shipment_id:
            return self._failure(BusinessError.SCHEDULING_MISSING_SHIPMENT_ID)

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

        contact, contact_failure = self._contact_from_payload(
            payload,
            tenant_settings=tenant_settings,
            turvo_shipment=turvo_shipment,
            sheet_customer=sheet_customer,
        )
        if contact_failure is not None:
            return contact_failure
        if contact is None:
            return self._failure(
                BusinessError.MISSING_RECIPIENT_EMAIL,
                customer_name=sheet_customer,
            )

        office_code = ascend_office_code_from_reference(reference_number=reference_number)
        ascend_settings = load_appointment_scheduling_settings(tenant_slug)
        if not ascend_settings.ascend_email or not ascend_settings.ascend_password:
            return self._failure(
                BusinessError.ASCEND_NOT_CONFIGURED,
                customer_name=sheet_customer,
            )

        try:
            auth = login_ascend_api(
                email=ascend_settings.ascend_email,
                password=ascend_settings.ascend_password,
            )
            access_token = str(auth.get("accessToken") or "")
        except AscendApiError as exc:
            if is_ascend_timeout(exc):
                failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
            else:
                failure = SchedulingFailure.from_ascend(
                    AscendError.LOGIN_FAILED,
                    status_code=str(exc.status_code or ""),
                )
            return IntakeResult(ok=False, failure=failure)

        try:
            ascend_shipment = fetched_shipment_details(
                reference_number=reference_number,
                access_token=access_token,
                office_code=office_code,
            )
        except AscendApiError as exc:
            if is_ascend_timeout(exc):
                failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
            else:
                failure = SchedulingFailure.from_ascend(
                    AscendError.SHIPMENT_FETCH_FAILED,
                    reference_number=reference_number,
                    status_code=str(exc.status_code or ""),
                )
            return IntakeResult(ok=False, failure=failure)

        try:
            appointments = get_loc_ref_for_ascend_slots(
                reference_number=reference_number,
                access_token=access_token,
                office_code=office_code,
            )
        except AscendApiError as exc:
            if is_ascend_timeout(exc):
                failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
            else:
                failure = SchedulingFailure.from_ascend(
                    AscendError.AVAILABILITY_FETCH_FAILED,
                    reference_number=reference_number,
                )
            return IntakeResult(ok=False, failure=failure)

        pickup_raw = pickup_dropoff_from_ascend_shipment(ascend_shipment)
        if pickup_raw.get("error"):
            return self._failure(
                BusinessError.ASCEND_PICKUP_DROPOFF_EXTRACT_FAILED,
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

        shipments_row_id = str(payload.get("shipments_row_id") or "").strip()
        if shipments_row_id:
            self._location_link.try_link_from_turvo_shipment_payload(
                turvo_shipment,
                shipments_row_id=shipments_row_id,
            )

        return IntakeResult(
            ok=True,
            shipment=turvo_shipment,
            ascend_shipment=ascend_shipment,
            customer_contact=contact,
            pickup_dropoff_data=pickup_dropoff,
            draft_static=draft_static,
            customer_name=sheet_customer,
            reference_number=reference_number,
            office_code=office_code,
            ascend_appointments=appointments,
        )

    @staticmethod
    def build_intake_state_patch(result: IntakeResult) -> dict[str, Any]:
        if not result.ok:
            return {}
        patch: dict[str, Any] = {}
        if result.shipment is not None:
            patch["shipment"] = result.shipment
        if result.ascend_shipment is not None:
            patch["ascend_shipment"] = result.ascend_shipment
        if result.customer_contact is not None:
            patch["customer_contact"] = result.customer_contact.model_dump(mode="json")
        if result.pickup_dropoff_data is not None:
            patch["pickup_dropoff_data"] = result.pickup_dropoff_data.model_dump(mode="json")
        if result.draft_static is not None:
            patch["draft_static"] = result.draft_static.model_dump(mode="json")
        if result.customer_name:
            patch["customer_name"] = result.customer_name
        if result.reference_number:
            patch["reference_number"] = result.reference_number
        if result.office_code is not None or result.ascend_appointments is not None:
            patch["ascend_context"] = {
                "office_code": result.office_code,
                "appointments": result.ascend_appointments,
            }
        return patch

    @staticmethod
    def _parse_cc(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [part.strip() for part in text.split(",") if part.strip()]

    def build_email_draft_from_state(self, state) -> EmailDraftResult:
        data = state.data or {}
        contact = data.get("customer_contact") or {}
        settings = self._settings(data.get("tenant_settings") or {})
        email_draft, appointment_payload = build_email_draft(
            pickup_dropoff=PickupDropoffData.model_validate(
                data.get("pickup_dropoff_data") or {}
            ),
            llm_decision=LlmAppointmentDecision.model_validate(
                data.get("llm_appointment_decision") or {}
            ),
            draft_static=DraftStatic.model_validate(data.get("draft_static") or {}),
            to_email=str(contact.get("email") or ""),
            cc=self._parse_cc(settings.email_cc),
            load_id=str(data.get("load_id") or ""),
            customer_name=str(data.get("customer_name") or ""),
        )
        return EmailDraftResult(
            email_draft=email_draft.model_dump(mode="json"),
            appointment_payload=appointment_payload.model_dump(mode="json"),
        )


def contact_from_rows_skip_reason(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> BusinessError | None:
    row = find_customer_sheet_row(rows, customer_name)
    if row is None:
        return BusinessError.MISSING_RECIPIENT_EMAIL
    if not is_email_appointment_mode(appointment_mode_from_row(row)):
        return BusinessError.APPOINTMENT_MODE_NOT_EMAIL
    contact = customer_contact_from_row(row)
    if contact is None or not contact.email:
        return BusinessError.MISSING_RECIPIENT_EMAIL
    return None


def missing_recipient_email_skip_reason(
    *,
    tenant_settings: dict[str, Any],
    shipment_payload: dict[str, Any],
) -> str | None:
    """Return a skip reason wire string when sheet/recipient pre-check fails; else None."""
    skip_reason, _contact = resolve_recipient_contact(
        tenant_settings=tenant_settings,
        shipment_payload=shipment_payload,
    )
    return skip_reason.value if skip_reason is not None else None


def resolve_recipient_contact(
    *,
    tenant_settings: dict[str, Any],
    shipment_payload: dict[str, Any],
) -> tuple[BusinessError | None, CustomerContactRow | None]:
    """Resolve recipient via sheet gquery (or local xlsx); return catalog error or contact."""
    settings = IntakeService._settings(tenant_settings)
    sheet_source = str(settings.appointment_data_source or "").strip()
    if not sheet_source:
        return BusinessError.MISSING_APPOINTMENT_DATA_SOURCE, None
    sheet_customer = delivery_stop_name_from_payload(shipment_payload) or ""
    try:
        rows = load_appointment_customer_rows(sheet_source, sheet_customer)
    except (OSError, GoogleSheetsError, ValueError):
        return BusinessError.APPOINTMENT_SHEET_UNREADABLE, None

    if skip := contact_from_rows_skip_reason(rows, sheet_customer):
        return skip, None
    row = find_customer_sheet_row(rows, sheet_customer)
    contact = customer_contact_from_row(row) if row is not None else None
    if contact is None or not contact.email:
        return BusinessError.MISSING_RECIPIENT_EMAIL, None
    return None, contact
