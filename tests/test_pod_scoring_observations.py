"""Tests for ``derive_pod_scoring_observations`` (LLM pages → scoring contract)."""

from __future__ import annotations

from app.services.pod_lifecycle.extraction import derive_pod_scoring_observations


def _page_with_receiver_sig(**overrides) -> dict:
    page = {
        "page_number": 1,
        "signatures": [
            {"owner": "receiver", "label": "Consignee Signature", "reasoning": "Ink in consignee box."}
        ],
        "proof_of_receipt": {
            "has_receiver_signature": True,
            "has_stamp": False,
            "has_delivery_sticker": False,
            "delivery_number": "007660706282",
            "reasoning": "Receiver signed in consignee box.",
        },
        "reference_ids": [{"label": "Delivery#", "value": "007660706282"}],
        "pallets_shipped": 37,
        "damage_detected": False,
        "damage_detail": "",
    }
    page.update(overrides)
    return page


def test_receiver_signature_sets_delivery_signature_present() -> None:
    obs = derive_pod_scoring_observations([_page_with_receiver_sig()])
    assert obs["delivery_signature_present"] is True


def test_driver_signature_only_does_not_count_as_delivery_proof() -> None:
    page = _page_with_receiver_sig(
        signatures=[{"owner": "driver", "label": "Driver Signature:", "reasoning": "Driver box."}],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": False,
            "has_delivery_sticker": False,
            "delivery_number": "",
            "reasoning": "No receiver evidence.",
        },
    )
    obs = derive_pod_scoring_observations([page])
    assert obs["delivery_signature_present"] is False


def test_stamp_counts_as_delivery_proof_without_receiver_signature() -> None:
    page = _page_with_receiver_sig(
        signatures=[],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": True,
            "has_delivery_sticker": False,
            "delivery_number": "",
            "reasoning": "Stamp says Received.",
        },
    )
    obs = derive_pod_scoring_observations([page])
    assert obs["delivery_signature_present"] is True


def test_delivery_sticker_counts_as_delivery_proof() -> None:
    page = _page_with_receiver_sig(
        signatures=[],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": False,
            "has_delivery_sticker": True,
            "delivery_number": "STICKER-99",
            "reasoning": "Walmart sticker affixed.",
        },
    )
    obs = derive_pod_scoring_observations([page])
    assert obs["delivery_signature_present"] is True
    assert "STICKER-99" in obs["extracted_reference_numbers"]


def test_multi_signature_page_only_receiver_counts_for_proof() -> None:
    page = _page_with_receiver_sig(
        signatures=[
            {"owner": "shipper", "label": "Shipper", "reasoning": "In shipper box."},
            {"owner": "carrier", "label": "Carrier", "reasoning": "In carrier box."},
            {"owner": "driver", "label": "Driver Signature:", "reasoning": "In driver box."},
        ],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": False,
            "has_delivery_sticker": False,
            "delivery_number": "",
            "reasoning": "No receiver evidence.",
        },
    )
    obs = derive_pod_scoring_observations([page])
    assert obs["delivery_signature_present"] is False


def test_no_pages_means_no_signature_evidence() -> None:
    obs = derive_pod_scoring_observations([])
    assert obs["delivery_signature_present"] is False


def test_reference_numbers_come_from_page_labels() -> None:
    obs = derive_pod_scoring_observations([_page_with_receiver_sig()])
    assert "007660706282" in obs["extracted_reference_numbers"]


def test_delivery_sticker_number_counts_as_a_reference_value() -> None:
    page = _page_with_receiver_sig(
        reference_ids=[],
        proof_of_receipt={
            "has_receiver_signature": False,
            "has_stamp": False,
            "has_delivery_sticker": True,
            "delivery_number": "STICKER-99",
            "reasoning": "Delivery sticker present.",
        },
    )
    obs = derive_pod_scoring_observations([page])
    assert "STICKER-99" in obs["extracted_reference_numbers"]


def test_missing_stop_times_gives_none_dates() -> None:
    obs = derive_pod_scoring_observations([_page_with_receiver_sig()])
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
    obs = derive_pod_scoring_observations([_page_with_receiver_sig()])
    assert obs["pickup_location"] is None
    assert obs["delivery_address"] is None


def test_pallets_shipped_takes_max_across_pages() -> None:
    pages = [_page_with_receiver_sig(pallets_shipped=10), _page_with_receiver_sig(pallets_shipped=37)]
    obs = derive_pod_scoring_observations(pages)
    assert obs["pallets_shipped"] == 37


def test_no_pallets_shipped_anywhere_is_none() -> None:
    page = _page_with_receiver_sig(pallets_shipped=None)
    obs = derive_pod_scoring_observations([page])
    assert obs["pallets_shipped"] is None


def test_damage_detected_true_with_detail_from_first_flagged_page() -> None:
    pages = [
        _page_with_receiver_sig(damage_detected=True, damage_detail="Torn box on pallet 3."),
        _page_with_receiver_sig(damage_detected=False, damage_detail=""),
    ]
    obs = derive_pod_scoring_observations(pages)
    assert obs["damage_detected"] is True
    assert obs["damage_detail"] == "Torn box on pallet 3."


def test_no_damage_detected_gives_none_detail() -> None:
    obs = derive_pod_scoring_observations([_page_with_receiver_sig()])
    assert obs["damage_detected"] is False
    assert obs["damage_detail"] is None


def test_non_dict_pages_entries_are_skipped_without_crashing() -> None:
    obs = derive_pod_scoring_observations([None, "not-a-page", _page_with_receiver_sig()])
    assert obs["delivery_signature_present"] is True


def test_pages_not_a_list_does_not_crash() -> None:
    obs = derive_pod_scoring_observations(None)
    assert obs["delivery_signature_present"] is False
    assert obs["extracted_reference_numbers"] == []


def test_packet_level_proof_across_multiple_pages() -> None:
    """Receiver sig on page 1, PO on page 2 — proof still detected at packet level."""
    page1 = {
        "page_number": 1,
        "signatures": [{"owner": "receiver", "label": "Consignee", "reasoning": "Ink present."}],
        "proof_of_receipt": {"has_receiver_signature": True, "has_stamp": False, "has_delivery_sticker": False},
    }
    page2 = {
        "page_number": 2,
        "signatures": [],
        "proof_of_receipt": {"has_receiver_signature": False, "has_stamp": False, "has_delivery_sticker": False},
        "reference_ids": [{"label": "PO#", "value": "PO-123"}],
    }
    obs = derive_pod_scoring_observations([page1, page2])
    assert obs["delivery_signature_present"] is True
