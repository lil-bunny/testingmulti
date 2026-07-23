"""Unit tests for appointment scheduling pure tools."""

from __future__ import annotations

from app.tools.appointment_scheduling.ascend_transforms import (
    llm_location_input_from_pickup_dropoff,
    pickup_dropoff_from_ascend_shipment,
)
from app.tools.appointment_scheduling.customer_contact import (
    customer_contact_from_rows,
    find_customer_sheet_row,
    is_email_appointment_mode,
    normalize_appointment_mode,
)
from app.tools.appointment_scheduling.draft_email import (
    build_draft_static_from_turvo,
    build_email_draft,
    is_costco_customer,
    is_del_appt_req_subject,
    parse_del_appt_req_subject_token,
)
from app.tools.appointment_scheduling.dates import (
    parse_proposed_appointment_date,
    proposed_wall_clock_to_utc,
)
from app.domain.appointment_scheduling.models import DraftStatic, LlmAppointmentDecision, PickupDropoffData


def test_pickup_dropoff_from_ascend_shipment():
    payload = {
        "totalCharge": "$1,234.50",
        "totalMiles": 500,
        "proNumber": "PRO1",
        "shipmentStops": [
            {
                "appointmentStart": "2026-07-01T15:00:00Z",
                "stopName": "Origin WH",
                "zipCode": "95814",
                "state": "CA",
                "poNumbers": "PO-9",
                "stopOrderTotalPallets": 12,
            },
            {
                "stopName": "Dest WH",
                "zipCode": "98101",
                "state": "WA",
            },
        ],
    }
    result = pickup_dropoff_from_ascend_shipment(payload)
    assert result["po_number"] == "PO-9"
    assert result["pallet_count"] == 12
    assert result["pickup_data"]["location"] == "Origin WH"


def test_normalize_appointment_mode() -> None:
    assert normalize_appointment_mode("Email") == "email"
    assert normalize_appointment_mode("  CALL  ") == "call"
    assert normalize_appointment_mode(None) == ""


def test_is_email_appointment_mode() -> None:
    assert is_email_appointment_mode("email") is True
    assert is_email_appointment_mode("call") is False


def test_find_customer_sheet_row() -> None:
    rows = [{"CUSTOMER": "Acme Corp", "APPOINTMENT MODE": "email"}]
    assert find_customer_sheet_row(rows, "acme corp") == rows[0]
    assert find_customer_sheet_row(rows, "Other") is None


def test_find_customer_sheet_row_prefers_email_over_portal_row() -> None:
    # Portal row appears first; the email row must still win so we don't skip.
    rows = [
        {"CUSTOMER": "Costco Wholesale", "APPOINTMENT MODE": "portal"},
        {"CUSTOMER": "Costco Wholesale", "APPOINTMENT MODE": "email"},
    ]
    assert find_customer_sheet_row(rows, "Costco Wholesale") == rows[1]


def test_find_customer_sheet_row_falls_back_to_first_when_no_email() -> None:
    rows = [
        {"CUSTOMER": "Costco Wholesale", "APPOINTMENT MODE": "portal"},
        {"CUSTOMER": "Costco Wholesale", "APPOINTMENT MODE": "call"},
    ]
    assert find_customer_sheet_row(rows, "Costco Wholesale") == rows[0]


def test_customer_contact_ignores_appointment_mode_column():
    rows = [
        {
            "CUSTOMER": "Costco Wholesale",
            "APPOINTMENT MODE": "portal",
            "CONTACT DETAILS(EMAILS)": "Ops <scheduling@costco.example>",
        }
    ]
    contact = customer_contact_from_rows(rows, "Costco Wholesale")
    assert contact is not None
    assert contact.email == "scheduling@costco.example"


def test_customer_contact_supports_shipment_details_sheet_columns():
    rows = [
        {
            "CUSTOMER": "COSTCO #960 DEPOT SC",
            "CONTACT DETAILS": "mitej@theagentic.ai",
            "TRANSIT TIME": "7 hrs 31 mins",
            "APPOINTMENT MODE": "email",
        }
    ]
    contact = customer_contact_from_rows(rows, "COSTCO #960 DEPOT SC")
    assert contact is not None
    assert contact.email == "mitej@theagentic.ai"
    assert contact.transit_time == "7 hrs 31 mins"


def test_costco_vs_standard_email_html():
    pickup = PickupDropoffData(
        po_number="PO-1",
        pallet_count=4,
        pickup_data={"date": "07/01/2026"},
        dropoff_data={},
    )
    llm = LlmAppointmentDecision(
        calculated_delivery_date="07/04/2026",
        calculated_delivery_weekday="SATURDAY",
    )
    static = DraftStatic(
        reference_number="DIAMOND-RPN-1",
        shipment_details="Ref details",
        commodity="DIAMOND PET FOODS",
        name="T3RA Logistics Team",
        email="mikey@t3ralogistics.com",
        phone="(916) 458-5833",
    )

    costco_draft, _ = build_email_draft(
        pickup_dropoff=pickup,
        llm_decision=llm,
        draft_static=static,
        to_email="to@example.com",
        cc=["cc@example.com"],
        load_id="63294",
        customer_name="Costco Wholesale",
    )
    assert "06:00" in costco_draft.full_html
    assert costco_draft.subject == 'DEL APPT REQ "DIAMOND-RPN-1"'

    standard_draft, payload = build_email_draft(
        pickup_dropoff=pickup,
        llm_decision=llm,
        draft_static=static,
        to_email="to@example.com",
        cc=[],
        load_id="63294",
        customer_name="Other Customer",
    )
    assert "PO#" in standard_draft.full_html
    assert standard_draft.subject == 'DEL APPT REQ "63294"'
    assert payload.reference_number == "DIAMOND-RPN-1"


def test_is_del_appt_req_subject() -> None:
    assert is_del_appt_req_subject('Re: DEL APPT REQ "63294"')
    assert is_del_appt_req_subject("del appt req")
    assert not is_del_appt_req_subject("Rate confirmation")
    assert not is_del_appt_req_subject("")


def test_parse_del_appt_req_subject_token() -> None:
    assert parse_del_appt_req_subject_token('Re: DEL APPT REQ "63294"') == "63294"
    assert (
        parse_del_appt_req_subject_token('Re: DEL APPT REQ "DIAMOND-RPN00008809"')
        == "DIAMOND-RPN00008809"
    )
    assert parse_del_appt_req_subject_token("DEL APPT REQ") is None
    assert parse_del_appt_req_subject_token("Re: POD attached") is None


def test_llm_location_input_from_pickup_dropoff():
    mapped = llm_location_input_from_pickup_dropoff(
        {
            "pickup_data": {"location": "A", "state_name": "CA", "date": "07/01/2026", "time": "10:00"},
            "dropoff_data": {"location": "B", "state_name": "WA"},
            "miles": 100,
        }
    )
    assert mapped["pickup_location"] == "A"
    assert mapped["miles"] == 100


def test_is_costco_customer():
    assert is_costco_customer("Costco Wholesale #584")
    # Email parity: Pet Food Experts is NOT treated as Costco (standard layout).
    assert not is_costco_customer("Pet Food Experts LLC")
    assert not is_costco_customer("Random Shipper")


def test_parse_proposed_appointment_date_accepts_us_and_iso():
    iso = parse_proposed_appointment_date("2026-07-30")
    us = parse_proposed_appointment_date("08/04/2026")
    assert iso is not None and iso.year == 2026 and iso.month == 7 and iso.day == 30
    assert us is not None and us.month == 8 and us.day == 4
    assert parse_proposed_appointment_date("") is None
    assert parse_proposed_appointment_date("not-a-date") is None


def test_proposed_wall_clock_to_utc_converts_stop_timezone():
    utc = proposed_wall_clock_to_utc(
        "07/04/2026",
        time_raw="06:00",
        timezone_name="America/Chicago",
    )
    assert utc is not None
    assert utc.hour == 11
    assert utc.minute == 0


def test_proposed_wall_clock_to_utc_date_only_defaults_midnight_utc():
    utc = proposed_wall_clock_to_utc("2026-07-30")
    assert utc == parse_proposed_appointment_date("2026-07-30")
