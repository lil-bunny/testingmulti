"""Unit tests for the PoD-vs-Turvo scoring engine (``score_pod``)."""

from __future__ import annotations

from app.domain.pod_lifecycle.pod_score_result import ScoredField, StopScore
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

_PICKUP_PO = "A1176371"
_DELIVERY_PO = "007660706282"


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
                TurvoPurchaseOrder(po_number=_PICKUP_PO, stop_type="pickup"),
                TurvoPurchaseOrder(po_number=_DELIVERY_PO, stop_type="delivery"),
            ]
        ),
        pickup_date=pickup_date,
        delivery_date=delivery_date,
        ordered_pallet_qty=ordered_pallet_qty,
        custom_id="62762",
    )


def _stop(result, stop_type: str) -> StopScore:
    stop = next((s for s in result.stops if s.stop_type == stop_type), None)
    assert stop is not None
    return stop


def _field(stop: StopScore, label: str) -> ScoredField:
    field = next((f for f in stop.fields if f.label == label), None)
    assert field is not None
    return field


def _ref_id_score(result, stop_type: str) -> int:
    stop = _stop(result, stop_type)
    return _field(stop, "reference_id").score


def _ref_id_total(result) -> int:
    return sum(
        f.score for s in result.stops for f in s.fields
        if f.label == "reference_id"
    )


def test_signature_absent_zeroes_only_signature_component() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": False,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }

    result = score_pod(observations, pod_inputs)

    delivery = _stop(result, "delivery")
    sig = _field(delivery, "signature")
    assert sig.score == 0
    assert sig.max_score == 60
    assert _ref_id_total(result) == 40
    assert result.final_score == 40
    assert result.needs_action is True


def test_signature_present_and_both_stops_reference_id_match_scores_100() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }

    result = score_pod(observations, pod_inputs)

    delivery = _stop(result, "delivery")
    sig = _field(delivery, "signature")
    assert sig.score == 60
    assert result.final_score == 100
    assert result.pass_threshold == 90
    assert result.needs_action is True
    assert _ref_id_score(result, "pickup") == 20
    assert _ref_id_score(result, "delivery") == 20


def test_reference_id_prorated_50_50() -> None:
    """Pickup 1/1 -> 20; delivery 1/2 -> 10; ref-id total 30/40."""
    pod_inputs = _inputs(
        purchase_orders=[
            TurvoPurchaseOrder(po_number=_PICKUP_PO, stop_type="pickup"),
            TurvoPurchaseOrder(po_number=_DELIVERY_PO, stop_type="delivery"),
            TurvoPurchaseOrder(po_number="EXTRA-DELIVERY", stop_type="delivery"),
        ]
    )
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }

    result = score_pod(observations, pod_inputs)

    pickup_ref = _field(_stop(result, "pickup"), "reference_id")
    assert pickup_ref.score == 20
    assert len(pickup_ref.comparisons) == 1
    assert pickup_ref.comparisons[0].matched is True

    delivery_ref = _field(_stop(result, "delivery"), "reference_id")
    assert delivery_ref.score == 10
    assert len(delivery_ref.comparisons) == 2

    assert _ref_id_total(result) == 30
    # signature 60 + ref 30 + pass2 contributes to remaining 10 (raw 0) = 90
    assert result.final_score == 90
    assert result.needs_action is True


def test_shipment_detail_fields_carry_source_and_target() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
        "delivery_date": "2026-07-21T13:00:00Z",
        "destination_location": "COSTCO # 766",
    }

    result = score_pod(observations, pod_inputs)

    delivery = _stop(result, "delivery")
    date_field = _field(delivery, "delivery_date")
    assert date_field.score == 10
    assert date_field.target == "2026-07-21T13:00:00Z"
    assert date_field.source == "2026-07-21T13:00:00Z"
    assert date_field.category == "shipment_detail"

    location = _field(delivery, "delivery_location")
    assert location.score == 5
    assert location.source == "COSTCO # 766"


def test_proration_pass2_fills_remaining_capacity() -> None:
    """ref-id fails (0) but shipment detail raw is 30 -> contribution = 30."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["NO-MATCH"],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        "destination_location": "COSTCO # 766",
        "destination_address": "25900 Heather Place, Wilsonville, OR",
    }

    result = score_pod(observations, pod_inputs)
    # ref_id = 0, detail_raw = 30, remaining = 40, contribution = 30
    # final = 60 + 0 + 30 = 90
    assert result.final_score == 90


def test_final_score_never_exceeds_100() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        "pickup_location": "Diamond Pet Foods",
        "pickup_address": "250 East Roth Road, Lathrop, CA",
        "destination_location": "COSTCO # 766",
        "destination_address": "25900 Heather Place, Wilsonville, OR",
    }
    result = score_pod(observations, pod_inputs)
    assert _ref_id_total(result) == 40
    assert result.final_score == 100
    assert result.max_score == 100


def test_blank_shipment_detail_field_scores_zero() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [],
        "destination_address": "",
    }
    result = score_pod(observations, pod_inputs)
    delivery = _stop(result, "delivery")
    addr_field = _field(delivery, "delivery_address")
    assert addr_field.score == 0
    assert addr_field.target == _DELIVERY.address
    assert addr_field.source is None


def test_pickup_stop_with_no_turvo_pos_has_zero_ref_id() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {"delivery_signature_present": True}
    result = score_pod(observations, pod_inputs)
    pickup_ref = _field(_stop(result, "pickup"), "reference_id")
    assert pickup_ref.score == 0
    assert pickup_ref.comparisons == []
    assert result.final_score == 60


def test_exceptions_do_not_affect_score() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
        "damage_detected": True,
        "damage_detail": "2 pallets damaged",
    }

    result = score_pod(observations, pod_inputs)

    assert result.final_score == 80
    assert result.needs_action is True
    assert result.exceptions is not None
    assert len(result.exceptions) == 1
    assert result.exceptions[0].exception_type == "damage"


def test_short_shipment_exception_detected() -> None:
    pod_inputs = _inputs(ordered_pallet_qty=14, purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
        "pallets_shipped": 13,
    }
    result = score_pod(observations, pod_inputs)
    assert result.exceptions is not None
    assert len(result.exceptions) == 1
    assert result.exceptions[0].exception_type == "short_shipment"
    assert result.final_score == 80


def test_over_shipment_exception_detected() -> None:
    pod_inputs = _inputs(ordered_pallet_qty=14, purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
        "pallets_shipped": 15,
    }
    result = score_pod(observations, pod_inputs)
    assert result.exceptions is not None
    assert result.exceptions[0].exception_type == "over_shipment"


def test_refused_delivery_is_prominently_classified() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    result = score_pod(
        {
            "delivery_signature_present": True,
            "extracted_reference_numbers": [_DELIVERY_PO],
            "damage_detected": True,
            "damage_detail": "Receiver refused delivery due to a broken pallet.",
        },
        pod_inputs,
    )

    assert result.final_score == 80
    assert result.needs_action is True
    assert result.exceptions is not None
    assert result.exceptions[0].exception_type == "refused_delivery"


def test_signature_only_on_delivery_stop() -> None:
    """Signature field exists only in delivery stop, not pickup."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
    }
    result = score_pod(observations, pod_inputs)

    pickup = _stop(result, "pickup")
    assert all(f.label != "signature" for f in pickup.fields)

    delivery = _stop(result, "delivery")
    sig = _field(delivery, "signature")
    assert sig.score == 60


def test_no_purchase_orders_fails_closed() -> None:
    pod_inputs = _inputs(purchase_orders=[])
    result = score_pod({"delivery_signature_present": True}, pod_inputs)
    assert result.final_score == 0
    assert result.stops == []
    assert result.needs_action is True


def test_reference_id_match_is_casefold_no_leading_zero_strip() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder("007660706282", "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["7660706282"],
    }
    result = score_pod(observations, pod_inputs)
    assert _ref_id_total(result) == 0
    assert result.final_score == 60

    observations_padded = {**observations, "extracted_reference_numbers": ["007660706282"]}
    result_padded = score_pod(observations_padded, pod_inputs)
    assert _ref_id_total(result_padded) == 20
    assert result_padded.final_score == 80


def test_comparisons_show_matched_and_unmatched_pos() -> None:
    pod_inputs = _inputs(
        purchase_orders=[
            TurvoPurchaseOrder(po_number=_PICKUP_PO, stop_type="pickup"),
            TurvoPurchaseOrder(po_number=_DELIVERY_PO, stop_type="delivery"),
            TurvoPurchaseOrder(po_number="UNPROVEN", stop_type="delivery"),
        ]
    )
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }
    result = score_pod(observations, pod_inputs)

    delivery_ref = _field(_stop(result, "delivery"), "reference_id")
    by_po = {c.po_number: c for c in delivery_ref.comparisons}
    assert by_po[_DELIVERY_PO].matched is True
    assert by_po[_DELIVERY_PO].source == _DELIVERY_PO
    assert by_po["UNPROVEN"].matched is False
    assert by_po["UNPROVEN"].source is None
    assert by_po["UNPROVEN"].target == "UNPROVEN"


def test_exceptions_omitted_when_empty() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }
    result = score_pod(observations, pod_inputs)
    assert result.exceptions is None


def test_stop_order_is_correct() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }
    result = score_pod(observations, pod_inputs)
    assert result.stops[0].stop_type == "pickup"
    assert result.stops[0].stop_order == 1
    assert result.stops[1].stop_type == "delivery"
    assert result.stops[1].stop_order == 2
