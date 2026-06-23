"""Pure driver-details tool helpers."""

from __future__ import annotations

from app.tools.driver_details import (
    DO_NOTHING,
    HAS_DETAILS,
    INSUFFICIENT,
    build_driver_details_result,
    can_create_tms_driver_contact,
    contact_row_name_phone,
    emails_match,
    has_partial_driver_fields,
    has_tms_searchable_fields,
    names_match,
    name_tokens_match,
    normalize_driver_details_decision,
    normalize_driver_reply_body,
    normalize_phone_digits,
    phone_duplicate_names_compatible,
    pick_phone_duplicate_contact,
    phones_match,
    render_driver_confirmation_html,
    validate_minimum_driver_fields,
)


def test_normalize_driver_reply_body_strips_html() -> None:
    assert normalize_driver_reply_body(body="<p>Driver: John</p>") == "Driver: John"


def test_normalize_driver_details_decision_unknown_is_do_nothing() -> None:
    assert normalize_driver_details_decision({"decision": "maybe"}) == DO_NOTHING


def test_validate_minimum_driver_fields_requires_name_and_contact() -> None:
    assert (
        validate_minimum_driver_fields({"name": "John", "phone": None, "email": None})
        == INSUFFICIENT
    )
    assert (
        validate_minimum_driver_fields(
            {"name": "John", "phone": "555-0100", "email": None}
        )
        == HAS_DETAILS
    )


def test_build_driver_details_result_downgrades_incomplete_has_details() -> None:
    result = build_driver_details_result(
        {
            "decision": HAS_DETAILS,
            "confidence": 0.9,
            "reason": "clear reply",
            "driver": {"name": "John", "phone": None, "email": None},
        }
    )
    assert result["decision"] == INSUFFICIENT
    assert result["driver"]["name"] == "John"


def test_normalize_phone_digits_us_number() -> None:
    assert normalize_phone_digits("+1 (454) 235-353") == "454235353"
    assert phones_match("+1454235353", "454235353")


def test_names_and_emails_match_case_insensitive() -> None:
    assert names_match("Virat", "virat")
    assert not names_match("Virat", "Anna")
    assert emails_match("A@B.com", "a@b.com")
    assert not emails_match("a@b.com", "c@d.com")


def test_name_tokens_match_partial_and_subset() -> None:
    assert name_tokens_match("John", "John Smith")
    assert name_tokens_match("John Smith", "John Smith")
    assert name_tokens_match("Smith", "John Smith")
    assert not name_tokens_match("John", "Jonathan Smith")
    assert not name_tokens_match("", "John Smith")
    assert not name_tokens_match("Smith", "John Doe")


def test_phone_duplicate_names_compatible() -> None:
    assert phone_duplicate_names_compatible(
        [{"name": "Alyssa"}, {"name": "Alyssa Wolf"}]
    )
    assert not phone_duplicate_names_compatible(
        [{"name": "John Smith"}, {"name": "John Williams"}]
    )


def test_pick_phone_duplicate_contact_prefers_richest_name() -> None:
    rows = [
        {"id": 640680, "name": "Alyssa", "phones": ["5122691730"]},
        {"id": 604186, "name": "Alyssa Wolf", "phones": ["5122691730"]},
    ]
    picked = pick_phone_duplicate_contact(rows)
    assert picked is not None
    assert picked["id"] == 604186


def test_pick_phone_duplicate_contact_same_name_picks_lower_id() -> None:
    rows = [
        {"id": 640680, "name": "Alyssa", "phones": ["5122691730"]},
        {"id": 604186, "name": "Alyssa", "phones": ["5122691730"]},
    ]
    picked = pick_phone_duplicate_contact(rows)
    assert picked is not None
    assert picked["id"] == 604186


def test_pick_phone_duplicate_contact_incompatible_returns_none() -> None:
    rows = [
        {"id": 640636, "name": "John Smith", "phones": ["9169170369"]},
        {"id": 640637, "name": "John Williams", "phones": ["9169170369"]},
    ]
    assert pick_phone_duplicate_contact(rows) is None


def test_has_tms_searchable_fields() -> None:
    assert has_tms_searchable_fields({"name": "anna", "phone": None, "email": None})
    assert has_tms_searchable_fields({"name": None, "phone": "555", "email": None})
    assert not has_tms_searchable_fields({"name": None, "phone": None, "email": "a@b.c"})


def test_can_create_tms_driver_contact() -> None:
    assert can_create_tms_driver_contact({"name": "anna", "phone": "555", "email": None})
    assert not can_create_tms_driver_contact({"name": "anna", "phone": None, "email": None})


def test_contact_row_name_phone() -> None:
    assert contact_row_name_phone({"name": "Virat", "phones": ["9989239823"]}) == (
        "Virat",
        "9989239823",
    )
    assert contact_row_name_phone({"name": "  ", "phones": []}) == (None, None)


def test_render_driver_confirmation_html() -> None:
    html = render_driver_confirmation_html(
        "<p>{driver_name}</p><p>{driver_phone}</p>",
        driver_name="anna",
        driver_phone="555-0100",
    )
    assert "anna" in html
    assert "555-0100" in html


def test_has_partial_driver_fields():
    assert has_partial_driver_fields({"name": "John", "phone": None, "email": None})
    assert has_partial_driver_fields({"name": None, "phone": "555", "email": None})
    assert not has_partial_driver_fields({"name": "John", "phone": "555", "email": None})
    assert not has_partial_driver_fields({"name": None, "phone": None, "email": None})


def test_build_driver_details_result_accepts_full_driver() -> None:
    result = build_driver_details_result(
        {
            "decision": HAS_DETAILS,
            "confidence": 0.95,
            "reason": "complete",
            "driver": {
                "name": "Jane Doe",
                "phone": "555-0199",
                "email": "jane@carrier.com",
            },
        }
    )
    assert result["decision"] == HAS_DETAILS
    assert result["driver"]["email"] == "jane@carrier.com"
