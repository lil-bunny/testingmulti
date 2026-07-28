"""Appointment scheduling email draft building tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.appointment_scheduling.models import DraftStatic, LlmAppointmentDecision, PickupDropoffData
from app.services.appointment_scheduling.intake_service import IntakeService


def test_build_email_draft_from_state_success():
    state = SimpleNamespace(
        data={
            "pickup_dropoff_data": PickupDropoffData(
                po_number="PO-22",
                pallet_count=8,
                pickup_data={"date": "07/01/2026"},
                dropoff_data={},
            ).model_dump(mode="json"),
            "llm_appointment_decision": LlmAppointmentDecision(
                calculated_delivery_date="07/04/2026",
                calculated_delivery_weekday="SATURDAY",
                pcs_pickup_date="07/01/2026",
            ).model_dump(mode="json"),
            "draft_static": DraftStatic(
                reference_number="DIAMOND-RPN-22",
                shipment_details="details",
                commodity="DIAMOND PET FOODS",
                name="T3RA Logistics Team",
                email="mikey@t3ralogistics.com",
                phone="(916) 458-5833",
            ).model_dump(mode="json"),
            "customer_contact": {"email": "customer@example.com"},
            "tenant_settings": {
                "appointment_scheduling": {
                    "emails": {
                        "to": ["primary@example.com"],
                        "cc": ["ops@example.com", "cc@example.com"],
                        "bcc": [],
                    }
                }
            },
            "load_id": "63294",
            "customer_name": "Acme",
        }
    )
    result = IntakeService().build_email_draft_from_state(state)
    assert result.email_draft["to"] == ["customer@example.com", "primary@example.com"]
    assert result.email_draft["cc"] == ["ops@example.com", "cc@example.com"]
    assert result.email_draft["bcc"] == []
    assert result.email_draft["subject"] == 'DEL APPT REQ "63294"'
    assert result.email_draft["full_html"]
    assert result.appointment_payload["reference_number"] == "DIAMOND-RPN-22"
    assert result.appointment_payload["proposed_delivery_at"] == "07/04/2026"


def test_build_email_draft_from_state_merges_to_dedupes_customer():
    state = SimpleNamespace(
        data={
            "pickup_dropoff_data": PickupDropoffData().model_dump(mode="json"),
            "llm_appointment_decision": LlmAppointmentDecision(
                calculated_delivery_date="07/04/2026",
                calculated_delivery_weekday="SATURDAY",
            ).model_dump(mode="json"),
            "draft_static": DraftStatic(
                reference_number="RPN-1",
                name="T3RA",
                email="mikey@t3ralogistics.com",
            ).model_dump(mode="json"),
            "customer_contact": {"email": "Customer@Example.com"},
            "tenant_settings": {
                "appointment_scheduling": {
                    "emails": {
                        "to": ["customer@example.com", "primary@example.com"],
                        "cc": [],
                        "bcc": ["bcc@example.com"],
                    }
                }
            },
            "load_id": "63294",
            "customer_name": "Acme",
        }
    )
    result = IntakeService().build_email_draft_from_state(state)
    assert result.email_draft["to"] == ["Customer@Example.com", "primary@example.com"]
    assert result.email_draft["bcc"] == ["bcc@example.com"]
