"""Tests for ``derive_pod_scoring_observations`` (LLM pages → scoring contract)."""

from __future__ import annotations

from app.services.pod_lifecycle.extraction import derive_pod_scoring_observations

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
    obs = derive_pod_scoring_observations([_delivery_page()])
    assert obs["delivery_signature_present"] is True


def test_driver_signature_on_delivery_page_does_not_count() -> None:
    page = _delivery_page(signature_owner="driver")
    obs = derive_pod_scoring_observations([page])
    assert obs["delivery_signature_present"] is False


def test_pickup_page_evidence_sets_pickup_signature_present_but_not_delivery() -> None:
    pickup_page = _delivery_page(page_stop_attribution="pickup", signature_owner="shipper")
    obs = derive_pod_scoring_observations([pickup_page])
    assert obs["pickup_signature_present"] is True
    assert obs["delivery_signature_present"] is False


def test_no_pages_means_no_signature_evidence() -> None:
    obs = derive_pod_scoring_observations([])
    assert obs["delivery_signature_present"] is False
    assert obs["pickup_signature_present"] is False


def test_reference_numbers_come_from_page_labels() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()])
    assert "007660706282" in obs["extracted_reference_numbers"]


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
    obs = derive_pod_scoring_observations([page])
    assert "STICKER-99" in obs["extracted_reference_numbers"]
    assert obs["delivery_signature_present"] is True  # sticker counts as delivery evidence


def test_missing_stop_times_gives_none_dates() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()])
    assert obs["pickup_date"] is None
    assert obs["delivery_date"] is None


def _location_page(**overrides) -> dict:
    page = {
        "page_number": 3,
        "location_blocks": [
            {
                "printed_label": "Ship From",
                "location_name": "Diamond Pet Foods",
                "address": "11908 Harlan Road\nLathrop, CA 95330",
            },
            {
                "printed_label": "Ship To",
                "location_name": "COSTCO #936 CBDSDTOL",
                "address": "8400 WEST SHERMAN\nTOLLESON, AZ 85353",
            },
        ],
    }
    page.update(overrides)
    return page


def test_ship_from_and_ship_to_blocks_populate_location_observations() -> None:
    obs = derive_pod_scoring_observations([_location_page()])
    assert obs["pickup_location"] == "Diamond Pet Foods"
    assert obs["pickup_address"] == "11908 Harlan Road\nLathrop, CA 95330"
    assert obs["delivery_location"] == "COSTCO #936 CBDSDTOL"
    assert obs["delivery_address"] == "8400 WEST SHERMAN\nTOLLESON, AZ 85353"


def test_fields_fallback_when_no_location_blocks() -> None:
    page = _location_page(location_blocks=[])
    page["fields"] = [
        {"key": "pickup_location", "value": "Diamond Pet Foods"},
        {"key": "pickup_address", "value": "11908 Harlan Road\nLathrop, CA 95330"},
        {"key": "delivery_location", "value": "COSTCO #936 CBDSDTOL"},
        {"key": "delivery_address", "value": "8400 WEST SHERMAN\nTOLLESON, AZ 85353"},
    ]
    obs = derive_pod_scoring_observations([page])
    assert obs["pickup_location"] == "Diamond Pet Foods"
    assert obs["delivery_location"] == "COSTCO #936 CBDSDTOL"


def test_location_blocks_win_over_earlier_page_fields() -> None:
    field_page = _location_page(location_blocks=[], page_number=1)
    field_page["fields"] = [{"key": "delivery_location", "value": "COSTCO ECOMMERCE"}]
    obs = derive_pod_scoring_observations([field_page, _location_page()])
    assert obs["delivery_location"] == "COSTCO #936 CBDSDTOL"


def test_no_location_evidence_gives_none_values() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()])
    assert obs["pickup_location"] is None
    assert obs["delivery_address"] is None


def test_pallets_shipped_takes_max_across_pages() -> None:
    pages = [_delivery_page(pallets_shipped=10), _delivery_page(pallets_shipped=37)]
    obs = derive_pod_scoring_observations(pages)
    assert obs["pallets_shipped"] == 37


def test_no_pallets_shipped_anywhere_is_none() -> None:
    page = _delivery_page(pallets_shipped=None)
    obs = derive_pod_scoring_observations([page])
    assert obs["pallets_shipped"] is None


def test_damage_detected_true_with_detail_from_first_flagged_page() -> None:
    pages = [
        _delivery_page(damage_detected=True, damage_detail="Torn box on pallet 3."),
        _delivery_page(damage_detected=False, damage_detail=""),
    ]
    obs = derive_pod_scoring_observations(pages)
    assert obs["damage_detected"] is True
    assert obs["damage_detail"] == "Torn box on pallet 3."


def test_no_damage_detected_gives_none_detail() -> None:
    obs = derive_pod_scoring_observations([_delivery_page()])
    assert obs["damage_detected"] is False
    assert obs["damage_detail"] is None


def test_non_dict_pages_entries_are_skipped_without_crashing() -> None:
    obs = derive_pod_scoring_observations([None, "not-a-page", _delivery_page()])
    assert obs["delivery_signature_present"] is True


def test_pages_not_a_list_does_not_crash() -> None:
    obs = derive_pod_scoring_observations(None)
    assert obs["delivery_signature_present"] is False
    assert obs["extracted_reference_numbers"] == []
