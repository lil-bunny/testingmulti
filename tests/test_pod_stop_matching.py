from app.integrations.turvo.pod_inputs import extract_pod_inputs_from_shipment
from app.services.pod_lifecycle.pod_scoring import score_pod
from app.services.pod_lifecycle.stop_matching import build_stop_aware_observations


def _shipment() -> dict:
    return {
        "details": {
            "globalRoute": [
                {
                    "id": "X4",
                    "name": "Lathrop Offsite - Harlan Warehouse",
                    "stopType": {"key": "1500", "value": "Pickup"},
                    "address": {"line1": "11908 Harlan Road", "city": "Lathrop", "state": "CA"},
                    "poNumbers": ["A1178441"],
                },
                {
                    "id": "WI",
                    "name": "COSTCO #936 CBDSDTOL",
                    "stopType": {"key": "1501", "value": "Delivery"},
                    "address": {"line1": "8400 WEST SHERMAN", "city": "TOLLESON", "state": "AZ"},
                    "poNumbers": ["009360713406"],
                },
            ]
        }
    }


def test_30397_style_bol_accumulates_po_pages_and_delivery_times() -> None:
    pages = [
        {
            "page_number": 2,
            "reference_ids": [
                {"label": "PO#", "value": "A1178441"},
                {"label": "Customer PO#", "value": "009360713406"},
            ],
            "fields": [
                {"key": "pickup_location", "value": "Lathrop"},
                {"key": "delivery_address", "value": "8400 WEST SHERMAN TOLLESON, AZ"},
            ],
            "signatures": [
                {"owner": "receiver", "label": "Consignee Signature", "reasoning": "Ink in consignee box."}
            ],
            "proof_of_receipt": {"has_receiver_signature": True},
            "stop_times": [
                {
                    "pickup_checkin_time": "",
                    "pickup_checkout_time": "",
                    "delivery_checkin_time": "2026-07-25T10:19:00Z",
                    "delivery_checkout_time": "2026-07-25T11:12:00Z",
                }
            ],
        },
        {
            "page_number": 3,
            "reference_ids": [
                {"label": "PO#", "value": "A1178441"},
                {"label": "Customer PO#", "value": "009360713406"},
            ],
            "fields": [
                {"key": "pickup_address", "value": "11908 Harlan Road Lathrop, CA 95330"},
                {"key": "delivery_address", "value": "8400 WEST SHERMAN TOLLESON, AZ 85353"},
            ],
            "signatures": [],
            "proof_of_receipt": {},
            "stop_times": [],
        },
    ]

    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(pages, inputs)
    score = score_pod(observations, inputs)

    assert observations["po_matches"]["A1178441"]["matched_pages"] == [2, 3]
    assert observations["po_matches"]["009360713406"]["matched_pages"] == [2, 3]
    assert observations["stop_times"] == [
        {
            "turvo_stop_id": "WI",
            "stop_type": "delivery",
            "observations": [
                {
                    "check_in": "2026-07-25T10:19:00Z",
                    "check_out": "2026-07-25T11:12:00Z",
                    "source_pages": [2],
                }
            ],
        }
    ]
    assert score.final_score == 100
    assert score.needs_action is True


def test_po_target_address_mismatch_requires_review() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "PO#", "value": "A1178441"}],
                "fields": [{"key": "pickup_address", "value": "99 Wrong Street, Reno, NV"}],
                "signatures": [
                    {"owner": "receiver", "label": "Consignee", "reasoning": "Ink present."}
                ],
                "proof_of_receipt": {"has_receiver_signature": True},
                "stop_times": [],
            }
        ],
        inputs,
    )
    score = score_pod(observations, inputs)

    assert observations["po_matches"]["A1178441"]["mismatched_pages"] == [1]
    assert score.needs_action is True


def test_delivery_stamp_counts_without_receiver_signature() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "Customer PO#", "value": "009360713406"}],
                "fields": [
                    {"key": "delivery_address", "value": "8400 West Sherman, Tolleson, AZ"}
                ],
                "signatures": [],
                "proof_of_receipt": {"has_stamp": True},
                "stop_times": [],
            }
        ],
        inputs,
    )

    assert observations["delivery_signature_present"] is True


def test_unconfirmed_po_stop_requires_review() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "PO#", "value": "A1178441"}],
                "fields": [],
                "signatures": [],
                "proof_of_receipt": {},
                "stop_times": [],
            }
        ],
        inputs,
    )
    score = score_pod(observations, inputs)

    assert score.needs_action is True
    assert "PO 009360713406 was not found in the POD packet." in score.review_reasons


def test_receiver_signature_without_po_match_still_scores() -> None:
    """Signature on page without PO — packet-level proof still gives 60 pts."""
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "signatures": [
                    {"owner": "receiver", "label": "Received by", "reasoning": "Name written."}
                ],
                "proof_of_receipt": {"has_receiver_signature": True},
                "reference_ids": [],
                "fields": [],
                "stop_times": [],
            }
        ],
        inputs,
    )

    assert observations["delivery_signature_present"] is True
    score = score_pod(observations, inputs)
    assert score.final_score >= 60


def test_sticker_on_different_page_than_po_still_scores() -> None:
    """Sticker on page 1, PO on page 2 — packet-level proof works."""
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "signatures": [],
                "proof_of_receipt": {"has_delivery_sticker": True, "has_stamp": False},
                "reference_ids": [],
                "fields": [],
                "stop_times": [],
            },
            {
                "page_number": 2,
                "reference_ids": [{"label": "Customer PO#", "value": "009360713406"}],
                "fields": [{"key": "delivery_address", "value": "8400 WEST SHERMAN TOLLESON, AZ"}],
                "signatures": [],
                "proof_of_receipt": {},
                "stop_times": [],
            },
        ],
        inputs,
    )

    assert observations["delivery_signature_present"] is True


def test_driver_signature_does_not_count_as_delivery_proof() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "Customer PO#", "value": "009360713406"}],
                "fields": [{"key": "delivery_address", "value": "8400 West Sherman, Tolleson, AZ"}],
                "signatures": [
                    {"owner": "driver", "label": "Driver Signature:", "reasoning": "Driver box."}
                ],
                "proof_of_receipt": {"has_receiver_signature": False, "has_stamp": False, "has_delivery_sticker": False},
                "stop_times": [],
            }
        ],
        inputs,
    )

    assert observations["delivery_signature_present"] is False


def test_pickup_po_mismatch_generates_review_reason() -> None:
    """Pickup PO mismatches now also generate review reasons."""
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [],
                "fields": [],
                "signatures": [],
                "proof_of_receipt": {},
                "stop_times": [],
            }
        ],
        inputs,
    )
    score = score_pod(observations, inputs)

    pickup_reasons = [r for r in (score.review_reasons or []) if "A1178441" in r]
    assert len(pickup_reasons) == 1
