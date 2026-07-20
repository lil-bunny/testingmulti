"""Appointment scheduling draft service tests."""

from __future__ import annotations

from app.domain.appointment_scheduling.models import DraftStatic, LlmSchedulingDecision, PickupDropoffData
from app.services.appointment_scheduling.draft_service import AppointmentSchedulingDraftService


def test_build_email_draft_success():
    service = AppointmentSchedulingDraftService()
    result = service.build_email_draft(
        pickup_dropoff=PickupDropoffData(
            po_number="PO-22",
            pallet_count=8,
            pickup_data={"date": "07/01/2026"},
            dropoff_data={},
        ),
        llm_decision=LlmSchedulingDecision(
            calculated_delivery_date="07/04/2026",
            calculated_delivery_weekday="SATURDAY",
            pcs_pickup_date="07/01/2026",
        ),
        draft_static=DraftStatic(
            reference_number="DIAMOND-RPN-22",
            shipment_details="details",
            commodity="DIAMOND PET FOODS",
            name="T3RA Logistics Team",
            email="mikey@t3ralogistics.com",
            phone="(916) 458-5833",
        ),
        to_email="customer@example.com",
        tenant_settings={"appointment_scheduling": {"email_cc": "ops@example.com, cc@example.com"}},
        load_id="63294",
        customer_name="Acme",
    )
    assert result.email_draft["to"] == "customer@example.com"
    assert result.email_draft["subject"] == 'DEL APPT REQ "63294"'
    assert result.email_draft["full_html"]
    assert result.scheduling_payload["reference_number"] == "DIAMOND-RPN-22"
    assert result.scheduling_payload["proposed_delivery_at"] == "07/04/2026"
