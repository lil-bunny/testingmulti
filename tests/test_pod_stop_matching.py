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
                {"key": "destination_address", "value": "8400 WEST SHERMAN TOLLESON, AZ"},
            ],
            "signature_owner": "receiver",
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
                {"key": "destination_address", "value": "8400 WEST SHERMAN TOLLESON, AZ 85353"},
            ],
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
    assert score.overall_status == "PASS"


def test_po_target_address_mismatch_requires_review_without_score_threshold() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "PO#", "value": "A1178441"}],
                "fields": [{"key": "pickup_address", "value": "99 Wrong Street, Reno, NV"}],
                "signature_owner": "receiver",
                "proof_of_receipt": {"has_receiver_signature": True},
                "stop_times": [],
            }
        ],
        inputs,
    )
    score = score_pod(observations, inputs)

    assert observations["po_matches"]["A1178441"]["mismatched_pages"] == [1]
    assert score.needs_action is True
    assert score.review_reasons


def test_delivery_stamp_counts_without_a_signature_owner_label() -> None:
    inputs = extract_pod_inputs_from_shipment(_shipment())
    observations = build_stop_aware_observations(
        [
            {
                "page_number": 1,
                "reference_ids": [{"label": "Customer PO#", "value": "009360713406"}],
                "fields": [
                    {"key": "destination_address", "value": "8400 West Sherman, Tolleson, AZ"}
                ],
                "signature_owner": "unknown",
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
                "proof_of_receipt": {},
                "stop_times": [],
            }
        ],
        inputs,
    )
    score = score_pod(observations, inputs)

    assert score.needs_action is True
    assert score.review_reasons == [
        "PO A1178441 has no page confirming its Turvo pickup stop.",
        "PO 009360713406 was not found in the POD packet.",
    ]
