"""Unit tests for the PoD-vs-Turvo scoring engine (``score_pod``)."""

from __future__ import annotations

from app.domain.pod_lifecycle.pod_score_result import PodStopScore
from app.domain.pod_lifecycle.validation_score import (
    DEFAULT_VALIDATION_STRATEGY,
    calculate_validation_score,
)
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


def _stop(result, stop_type: str) -> PodStopScore:
    stop = next((item for item in result.stops if item.stop_type == stop_type), None)
    assert stop is not None
    assert isinstance(stop, PodStopScore)
    return stop


def test_signature_is_document_level_and_absent_zeroes_only_signature_component() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": False,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }

    result = score_pod(observations, pod_inputs)

    assert result.signature.score == 0
    assert result.signature.max_score == 60
    # Reference-id is scored independently of the signature gate.
    assert result.validation.ref_id_score == 40
    assert result.final_score == 40
    assert result.overall_status == "FAIL"
    assert result.needs_action is True


def test_signature_present_and_both_stops_reference_id_match_scores_100() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
    }

    result = score_pod(observations, pod_inputs)

    assert result.signature.score == 60
    assert result.final_score == 100
    assert result.overall_status == "PASS"
    assert result.needs_action is True
    pickup = _stop(result, "pickup")
    assert pickup.reference_id.score == 20
    assert pickup.reference_id.max_score == 20
    delivery = _stop(result, "delivery")
    assert delivery.reference_id.score == 20


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

    pickup = _stop(result, "pickup")
    assert pickup.po_total == 1
    assert pickup.po_matched == 1
    assert pickup.reference_id.score == 20

    delivery = _stop(result, "delivery")
    assert delivery.po_total == 2
    assert delivery.po_matched == 1
    assert delivery.reference_id.score == 10

    assert result.validation.ref_id_score == 30
    # Pass 2 raw is empty here, so every strategy yields signature 60 + ref 30.
    assert result.final_score == 90
    assert result.overall_status == "PASS"
    assert result.needs_action is True


def test_pass2_fields_are_always_scored_and_carry_both_sides() -> None:
    """Pass 2 keeps its real score even when reference-id already matched."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_DELIVERY_PO],
        "delivery_date": "2026-07-21T13:00:00Z",
        "consignee_name": "COSTCO # 766",
    }

    result = score_pod(observations, pod_inputs)

    delivery = _stop(result, "delivery")
    assert delivery.reference_id.score == 20
    date_field = next(f for f in delivery.diff if f.label == "delivery_date")
    assert date_field.score == 10
    assert date_field.turvo_value == "2026-07-21T13:00:00Z"
    assert date_field.pod_value == "2026-07-21T13:00:00Z"
    consignee = next(f for f in delivery.diff if f.label == "consignee_name")
    assert consignee.score == 5
    assert consignee.turvo_value == "COSTCO # 766"
    assert consignee.pod_value == "COSTCO # 766"
    assert result.validation.pass2_raw_score == 15


def test_validation_bucket_follows_active_strategy() -> None:
    """ref-id fails (0) but Pass 2 raw is 30 -> strategy decides the bucket."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["NO-MATCH"],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        "consignee_name": "COSTCO # 766",
        "consignee_address": "25900 Heather Place, Wilsonville, OR",
    }

    assert score_pod(observations, pod_inputs, strategy="fallback_swap").final_score == 90
    assert score_pod(observations, pod_inputs, strategy="blended_proration").final_score == 90
    assert score_pod(observations, pod_inputs, strategy="informational_pass2").final_score == 60

    default = score_pod(observations, pod_inputs)
    expected = 60 + calculate_validation_score(
        0, 30, strategy=DEFAULT_VALIDATION_STRATEGY
    ).score
    assert default.final_score == expected


def test_validation_bucket_never_exceeds_100() -> None:
    pod_inputs = _inputs()
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [_PICKUP_PO, _DELIVERY_PO],
        "pickup_date": "2026-07-20T15:00:00Z",
        "delivery_date": "2026-07-21T13:00:00Z",
        "shipper_name": "Diamond Pet Foods",
        "shipper_address": "250 East Roth Road, Lathrop, CA",
        "consignee_name": "COSTCO # 766",
        "consignee_address": "25900 Heather Place, Wilsonville, OR",
    }
    result = score_pod(observations, pod_inputs, strategy="blended_proration")
    assert result.validation.ref_id_score == 40
    assert result.validation.pass2_raw_score == 40
    assert result.final_score == 100
    assert result.max_score == 100


def test_blank_diff_field_scores_zero_for_that_field() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": [],
        "consignee_address": "",
    }
    result = score_pod(observations, pod_inputs)
    delivery = _stop(result, "delivery")
    consignee_address_field = next(f for f in delivery.diff if f.label == "consignee_address")
    assert consignee_address_field.score == 0
    assert consignee_address_field.turvo_value == _DELIVERY.address
    assert consignee_address_field.pod_value is None


def test_pickup_stop_with_no_turvo_pos_has_zero_ref_id() -> None:
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {"delivery_signature_present": True}
    result = score_pod(observations, pod_inputs)
    pickup = _stop(result, "pickup")
    assert pickup.po_total == 0
    assert pickup.po_matched == 0
    assert pickup.reference_id.score == 0
    assert result.validation.ref_id_score == 0
    assert result.final_score == 60


def test_exceptions_do_not_affect_score_but_force_needs_action() -> None:
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
    assert result.overall_status == "FAIL"
    assert result.needs_action is True
    assert result.exceptions[0].exception_type == "refused_delivery"


def test_pickup_signature_flag_is_ignored_by_scoring() -> None:
    """Pickup has no signature concept in the result; the flag is never scored."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder(_DELIVERY_PO, "delivery")])
    observations = {
        "delivery_signature_present": True,
        "pickup_signature_present": False,
        "extracted_reference_numbers": [_DELIVERY_PO],
    }
    result = score_pod(observations, pod_inputs)
    assert result.signature.score == 60
    assert result.remarks == []
    assert not hasattr(result, "pickup_signature_present")


def test_no_purchase_orders_fails_closed() -> None:
    pod_inputs = _inputs(purchase_orders=[])
    result = score_pod({"delivery_signature_present": True}, pod_inputs)
    assert result.final_score == 0
    assert result.stops == []
    assert result.needs_action is True


def test_reference_id_match_is_trim_and_casefold_only_no_leading_zero_strip() -> None:
    """Locked decision: no leading-zero stripping — a dropped-zero sticker value fails."""
    pod_inputs = _inputs(purchase_orders=[TurvoPurchaseOrder("007660706282", "delivery")])
    observations = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["7660706282"],  # zeros dropped, e.g. sticker OCR
    }
    result = score_pod(observations, pod_inputs)
    # Ref-id fails; Pass 2 is all blank -> signature only = 60.
    assert result.validation.ref_id_score == 0
    assert result.final_score == 60

    observations_padded = {**observations, "extracted_reference_numbers": ["007660706282"]}
    result_padded = score_pod(observations_padded, pod_inputs)
    assert result_padded.validation.ref_id_score == 20
    assert result_padded.final_score == 80


def test_po_scores_are_audit_evidence_per_turvo_po() -> None:
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
    by_number = {po.po_number: po for po in result.po_scores}
    assert by_number[_PICKUP_PO].matched is True
    assert by_number[_DELIVERY_PO].matched is True
    assert by_number["UNPROVEN"].matched is False
