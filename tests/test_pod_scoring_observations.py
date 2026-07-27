"""Tests for ``derive_pod_scoring_observations`` (LLM pages → scoring contract)."""

from __future__ import annotations

from app.services.pod_lifecycle.extraction import derive_pod_scoring_observations

_BASE_POD_DATA = {
    "pickup_location": "Diamond Pet Foods - 95330 (Roth)",
    "pickup_address": "250 East Roth Road, Lathrop, CA",
    "destination_location": "COSTCO # 766",
    "destination_address": "25900 HEATHER PLACE, WILSONVILLE, OR",
    "po_number": "A1176371",
    "stop_times": [
        {
            "pickup_checkin_time": "2026-07-20T15:00:00Z",
            "pickup_checkout_time": "",
            "delivery_checkin_time": "",
            "delivery_checkout_time": "2026-07-21T13:00:00Z",
        }
    ],
}


def _delivery_page(**overrides) -> dict:
    page = {
        "page_number": 1,
        "page_stop_attribution": "delivery",
        "signature_owner": "receiver",
        "proof_of_receipt": {
            "has_receiver_signature": True,
            "has_stamp": False,
            "has_delivery_sticker": False,
            "delivery_number": "007660706282",
        },
        "reference_ids": [{"label": "Delivery#", "value": "007660706282"}],
        "pallets_shipped": 37,
        "damage_detected": False,
        "damage_detail": "",
    }
    page.update(overrides)
    return page


def test_delivery_receiver_signature_sets_delivery_signature_present() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()], _BASE_POD_DATA)
    assert obs["delivery_signature_present"] is True


def test_driver_signature_on_delivery_page_does_not_count() -> None:
    page = _delivery_page(signature_owner="driver")
    obs = derive_pod_scoring_observations([page], _BASE_POD_DATA)
    assert obs["delivery_signature_present"] is False


def test_pickup_page_evidence_sets_pickup_signature_present_but_not_delivery() -> None:
    pickup_page = _delivery_page(page_stop_attribution="pickup", signature_owner="shipper")
    obs = derive_pod_scoring_observations([pickup_page], _BASE_POD_DATA)
    assert obs["pickup_signature_present"] is True
    assert obs["delivery_signature_present"] is False


def test_no_pages_means_no_signature_evidence() -> None:
    obs = derive_pod_scoring_observations([], _BASE_POD_DATA)
    assert obs["delivery_signature_present"] is False
    assert obs["pickup_signature_present"] is False


def test_reference_numbers_combine_page_labels_and_mapped_po_number() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()], _BASE_POD_DATA)
    assert "007660706282" in obs["extracted_reference_numbers"]
    assert "A1176371" in obs["extracted_reference_numbers"]


def test_delivery_sticker_number_counts_as_a_reference_value() -> None:
    page = _delivery_page(
        reference_ids=[],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": False,
            "has_delivery_sticker": True,
            "delivery_number": "STICKER-99",
        },
    )
    obs = derive_pod_scoring_observations([page], _BASE_POD_DATA)
    assert "STICKER-99" in obs["extracted_reference_numbers"]
    assert obs["delivery_signature_present"] is True  # sticker counts as delivery evidence


def test_shipper_and_consignee_fields_pass_through_from_mapped_pod_data() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()], _BASE_POD_DATA)
    assert obs["shipper_name"] == "Diamond Pet Foods - 95330 (Roth)"
    assert obs["shipper_address"] == "250 East Roth Road, Lathrop, CA"
    assert obs["consignee_name"] == "COSTCO # 766"
    assert obs["consignee_address"] == "25900 HEATHER PLACE, WILSONVILLE, OR"


def test_dates_derived_from_first_available_stop_time() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()], _BASE_POD_DATA)
    assert obs["pickup_date"] == "2026-07-20T15:00:00Z"
    assert obs["delivery_date"] == "2026-07-21T13:00:00Z"


def test_missing_stop_times_gives_none_dates() -> None:
    pod_data = {**_BASE_POD_DATA, "stop_times": []}
    obs = derive_pod_scoring_observations([_delivery_page()], pod_data)
    assert obs["pickup_date"] is None
    assert obs["delivery_date"] is None


def test_pallets_shipped_takes_max_across_pages() -> None:
    pages = [_delivery_page(pallets_shipped=10), _delivery_page(pallets_shipped=37)]
    obs = derive_pod_scoring_observations(pages, _BASE_POD_DATA)
    assert obs["pallets_shipped"] == 37


def test_no_pallets_shipped_anywhere_is_none() -> None:
    page = _delivery_page(pallets_shipped=None)
    obs = derive_pod_scoring_observations([page], _BASE_POD_DATA)
    assert obs["pallets_shipped"] is None


def test_damage_detected_true_with_detail_from_first_flagged_page() -> None:
    pages = [
        _delivery_page(damage_detected=True, damage_detail="Torn box on pallet 3."),
        _delivery_page(damage_detected=False, damage_detail=""),
    ]
    obs = derive_pod_scoring_observations(pages, _BASE_POD_DATA)
    assert obs["damage_detected"] is True
    assert obs["damage_detail"] == "Torn box on pallet 3."


def test_no_damage_detected_gives_none_detail() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()], _BASE_POD_DATA)
    assert obs["damage_detected"] is False
    assert obs["damage_detail"] is None


def test_non_dict_pages_entries_are_skipped_without_crashing() -> None:
    obs = derive_pod_scoring_observations([None, "not-a-page", _delivery_page()], _BASE_POD_DATA)
    assert obs["delivery_signature_present"] is True


def test_pages_not_a_list_does_not_crash() -> None:
    obs = derive_pod_scoring_observations(None, _BASE_POD_DATA)
    assert obs["delivery_signature_present"] is False
    assert obs["extracted_reference_numbers"] == ["A1176371"]
