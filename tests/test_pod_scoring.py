"""Unit tests for the PoD-vs-Turvo scoring engine (``score_pod``)."""

from __future__ import annotations

from app.integrations.turvo.pod_inputs import TurvoPurchaseOrder, TurvoShipmentPodInputs, TurvoStop
from app.services.pod_lifecycle.pod_scoring import score_pod

_PICKUP = TurvoStop(
    name="Diamond Pet Foods - 95330 (Roth)",
    address="250 East Roth Road, Lathrop, CA, US",
    po_numbers=["A1176371"],
    time_zone="America/Los_Angeles",
)
_DELIVERY = TurvoStop(
    name="COSTCO # 766",
    address="25900 HEATHER PLACE, WILSONVILLE, OR, US",
    po_numbers=["007660706282"],
    time_zone="America/Los_Angeles",
)


def _inputs(
    *,
    purchase_orders: list[TurvoPurchaseOrder] | None = None,
    pickup_date: str | None = "2026-07-20T15:00:00Z",
    delivery_date: str | None = "2026-07-21T13:00:00Z",
    ordered_pallet_qty: int | None = 37,
) -> TurvoShipmentPodInputs:
    return TurvoShipmentPodInputs(
        is_single_stop=True,
        pickup=_PICKUP,
        delivery=_DELIVERY,
        purchase_orders=(
            purchase_orders
            if purchase_orders is not None
            else [
                TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup"),
                TurvoPurchaseOrder(po_number="007660706282", stop_type="delivery"),
            ]
        ),
        pickup_date=pickup_date,
        delivery_date=delivery_date,
        ordered_pallet_qty=ordered_pallet_qty,
        custom_id="62762",
    )


def test_delivery_signature_absent_fails_all_pos_without_running_pass2() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": False,
        "extracted_reference_numbers": ["A1176371", "007660706282"],
    }

    result = score_pod(observations, pod_inputs)

    assert result.final_score == 0
    assert result.needs_action is True
    assert result.overall_status == "FAIL"
    for po_score in result.po_scores:
        assert po_score.po_total == 0
        assert po_score.pass2 is None


def test_signature_present_and_reference_id_match_scores_100() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
    }

    result = score_pod(observations, pod_inputs)

    assert result.final_score == 100
    assert result.needs_action is True
    assert result.overall_status == "PASS"
    assert result.po_scores[0].po_total == 100
    assert result.po_scores[0].pass2 is None


def test_reference_id_fails_full_pass2_recovers_to_100() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["NO-MATCH"],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        "shipper_name": "Diamond Pet Foods",
        "shipper_address": "250 East Roth Road, Lathrop, CA",
        "consignee_name": "COSTCO # 766",
        "consignee_address": "25900 Heather Place, Wilsonville, OR",
    }

    result = score_pod(observations, pod_inputs)

    assert result.po_scores[0].po_total == 100
    assert result.final_score == 100
    assert result.needs_action is True
    assert result.overall_status == "PASS"
    assert result.po_scores[0].pass2 is not None


def test_reference_id_fails_partial_pass2_dates_only_scores_80() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["NO-MATCH"],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        # shipper/consignee left blank -> 0 for those 4 fields
    }

    result = score_pod(observations, pod_inputs)

    assert result.po_scores[0].po_total == 80
    assert result.final_score == 80
    assert result.needs_action is True
    assert result.overall_status == "FAIL"


def test_blank_address_in_pass2_scores_zero_for_that_field() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [],
        "shipper_address": "",
    }
    result = score_pod(observations, pod_inputs)
    shipper_address_field = next(f for f in result.po_scores[0].pass2 if f.label == "shipper_address")
    assert shipper_address_field.points_awarded == 0


def test_spelling_variation_in_pass2_still_passes_via_token_overlap() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [],
        "consignee_name": "Costco Wholesale #766",  # spelling variant of "COSTCO # 766"
    }
    result = score_pod(observations, pod_inputs)
    consignee_name_field = next(f for f in result.po_scores[0].pass2 if f.label == "consignee_name")
    assert consignee_name_field.points_awarded == 5


def test_multi_po_pro_rating_matches_real_sample_shape() -> None:
    """PO A1176371 (pickup) ref-id passes; PO 007660706282 (delivery) fails ref-id,
    Pass 2 recovers dates only -> final = ((100) + (60+20)) / 2 = 90 -> PASS."""
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
    }

    result = score_pod(observations, pod_inputs)

    assert result.final_score == 90
    assert result.needs_action is True
    assert result.overall_status == "PASS"


def test_classic_doc_example_two_pos_one_signature_fails() -> None:
    """Doc example: PO-1 signature PASSED, PO-2 signature FAILED -> (60+0)/2 = 30 field.
    Modeled here as delivery signature absent entirely (both fail since it's shared),
    so instead we exercise the equivalent case: one PO fully proven, one fully unproven."""
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
        # No pass2 data at all for the other PO.
    }

    result = score_pod(observations, pod_inputs)

    po_by_number = {po.po_number: po for po in result.po_scores}
    assert po_by_number["A1176371"].po_total == 100
    assert po_by_number["007660706282"].po_total == 60  # signature only, Pass 2 all blank
    assert result.final_score == 80


def test_turvo_po_with_no_pod_proof_contributes_zero() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="UNPROVEN", stop_type="delivery")])
    observations = {"delivery_signature_present": False}
    result = score_pod(observations, pod_inputs)
    assert result.po_scores[0].po_total == 0
    assert result.final_score == 0


def test_exceptions_do_not_affect_score_but_force_needs_action() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
        "damage_detected": True,
        "damage_detail": "2 pallets damaged",
    }

    result = score_pod(observations, pod_inputs)

    assert result.final_score == 100
    assert result.needs_action is True
    assert len(result.exceptions) == 1
    assert result.exceptions[0].exception_type == "damage"


def test_short_shipment_exception_detected() -> None:
    pod_inputs = _inputs(ordered_pallet_qty=14, purchase_orders=[TurvoPurchaseOrder("A1176371", "pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
        "pallets_shipped": 13,
    }
    result = score_pod(observations, pod_inputs)
    assert result.exceptions == [
        result.exceptions[0]
    ]  # sanity: exactly one exception present
    assert result.exceptions[0].exception_type == "short_shipment"
    assert result.final_score == 100


def test_over_shipment_exception_detected() -> None:
    pod_inputs = _inputs(ordered_pallet_qty=14, purchase_orders=[TurvoPurchaseOrder("A1176371", "pickup")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371"],
        "pallets_shipped": 15,
    }
    result = score_pod(observations, pod_inputs)
    assert result.exceptions[0].exception_type == "over_shipment"


def test_refused_delivery_is_prominently_classified() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder("A1176371", "pickup")])
    result = score_pod(
        {
            "delivery_signature_present": True,
            "extracted_reference_numbers": ["A1176371"],
            "damage_detected": True,
            "damage_detail": "Receiver refused delivery due to a broken pallet.",
        },
        pod_inputs,
    )

    assert result.final_score == 100
    assert result.overall_status == "PASS"
    assert result.needs_action is True
    assert result.exceptions[0].exception_type == "refused_delivery"


def test_pickup_signature_missing_adds_remark_without_affecting_score() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder("A1176371", "pickup")])
    observations = {
        "delivery_signature_present": True,
        "pickup_signature_present": False,
        "extracted_reference_numbers": ["A1176371"],
    }
    result = score_pod(observations, pod_inputs)
    assert result.final_score == 100
    assert "Pickup signature not present." in result.remarks


def test_no_purchase_orders_fails_closed() -> None:
    pod_inputs = _inputs(purchase_orders=[])
    result = score_pod({"delivery_signature_present": True}, pod_inputs)
    assert result.final_score == 0
    assert result.needs_action is True


def test_reference_id_match_is_trim_and_casefold_only_no_leading_zero_strip() -> None:
    """Locked decision: no leading-zero stripping — a dropped-zero sticker value fails."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder("007660706282", "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["7660706282"],  # zeros dropped, e.g. sticker OCR
    }
    result = score_pod(observations, pod_inputs)
    # Ref-id fails to match exactly; Pass 2 runs (all blank here) -> signature only = 60.
    assert result.po_scores[0].po_total == 60

    observations_padded = {**observations, "extracted_reference_numbers": ["007660706282"]}
    result_padded = score_pod(observations_padded, pod_inputs)
    assert result_padded.po_scores[0].po_total == 100
