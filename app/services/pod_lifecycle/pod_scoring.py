"""PoD-vs-Turvo scoring engine (pure; no DB/HTTP).

LLM supplies ``pod_observations``; this module applies the deterministic score.
Flow per PO: delivery-signature gate (60) → ref-id match (40) → else Pass 2
(dates + shipper/consignee text). Final score is the mean of PO totals;
exceptions (damage/short/over) set ``needs_action`` but never change points.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.pod_lifecycle.pod_score_result import (
    PASS_THRESHOLD,
    PodException,
    PodFieldResult,
    PodPurchaseOrderScore,
    PodScoreResult,
    ScoreResult,
)
from app.integrations.turvo.pod_inputs import TurvoPurchaseOrder, TurvoShipmentPodInputs

_PASS2_DATE_POINTS = 10
_PASS2_TEXT_POINTS = 5
_IDENTIFIABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


def score_pod(
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
) -> PodScoreResult:
    """
    Score a PoD against Turvo shipment inputs. Pure and deterministic.

    Outcomes: mean PO total → PASS/FAIL at ``PASS_THRESHOLD``; missing Turvo POs
    or a FAIL (or any exception) sets ``needs_action``.
    """
    exceptions = _exceptions_from_observations(pod_observations, turvo_inputs)
    pickup_signature_present = bool(pod_observations.get("pickup_signature_present", True))
    remarks = [] if pickup_signature_present else ["Pickup signature not present."]

    if not turvo_inputs.purchase_orders:
        remarks.append("No Turvo PO found for this shipment; cannot score.")
        return PodScoreResult(
            po_scores=[],
            final_score=0,
            result="FAIL",
            exceptions=exceptions,
            needs_action=True,
            pickup_signature_present=pickup_signature_present,
            remarks=remarks,
        )

    delivery_signature_present = bool(pod_observations.get("delivery_signature_present"))
    po_scores = [
        _score_purchase_order(po, delivery_signature_present, pod_observations, turvo_inputs)
        for po in turvo_inputs.purchase_orders
    ]
    # Pro-rated sum of each field-PO combination reduces to the mean PO total,
    # since each PO's total is itself the sum of its field scores.
    final_score = round(sum(po.po_total for po in po_scores) / len(po_scores))
    result: ScoreResult = "PASS" if final_score >= PASS_THRESHOLD else "FAIL"
    needs_action = bool(exceptions) or result == "FAIL"

    return PodScoreResult(
        po_scores=po_scores,
        final_score=final_score,
        result=result,
        exceptions=exceptions,
        needs_action=needs_action,
        pickup_signature_present=pickup_signature_present,
        remarks=remarks,
    )


def _score_purchase_order(
    po: TurvoPurchaseOrder,
    delivery_signature_present: bool,
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
) -> PodPurchaseOrderScore:
    """
    Score one Turvo PO: shared delivery-signature gate, then ref-id or Pass 2.

    Missing delivery signature zeros the PO (Pass 2 never runs). Ref-id any-match
    awards 40; otherwise Pass 2 recovers up to 40 via dates + stop text fields.
    """
    if not delivery_signature_present:
        pass1 = [
            PodFieldResult(
                label="signature",
                points_awarded=0,
                points_possible=60,
                remark="No receiver signature, delivery stamp, or delivery sticker detected.",
            ),
            PodFieldResult(
                label="reference_id",
                points_awarded=0,
                points_possible=40,
                remark="Not evaluated: Pass 1 signature check failed.",
            ),
        ]
        return PodPurchaseOrderScore(
            po_number=po.po_number, stop_type=po.stop_type, pass1=pass1, pass2=None, po_total=0
        )

    signature_field = PodFieldResult(
        label="signature",
        points_awarded=60,
        points_possible=60,
        remark="Receiver signature, delivery stamp, or delivery sticker present.",
    )

    if _reference_id_matches(po.po_number, pod_observations):
        reference_field = PodFieldResult(
            label="reference_id",
            points_awarded=40,
            points_possible=40,
            remark=f"POD reference number matches Turvo PO {po.po_number}.",
        )
        return PodPurchaseOrderScore(
            po_number=po.po_number,
            stop_type=po.stop_type,
            pass1=[signature_field, reference_field],
            pass2=None,
            po_total=100,
        )

    reference_field = PodFieldResult(
        label="reference_id",
        points_awarded=0,
        points_possible=40,
        remark=f"No POD reference number matches Turvo PO {po.po_number}; running Pass 2.",
    )
    pass2 = _score_pass2(turvo_inputs, pod_observations)
    po_total = signature_field.points_awarded + sum(field.points_awarded for field in pass2)
    return PodPurchaseOrderScore(
        po_number=po.po_number,
        stop_type=po.stop_type,
        pass1=[signature_field, reference_field],
        pass2=pass2,
        po_total=po_total,
    )


def _score_pass2(
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> list[PodFieldResult]:
    return [
        _date_field(
            "pickup_date",
            turvo_inputs.pickup_date,
            pod_observations.get("pickup_date"),
            turvo_inputs.pickup.time_zone,
        ),
        _date_field(
            "delivery_date",
            turvo_inputs.delivery_date,
            pod_observations.get("delivery_date"),
            turvo_inputs.delivery.time_zone,
        ),
        _identifiable_text_field(
            "shipper_name", turvo_inputs.pickup.name, pod_observations.get("shipper_name")
        ),
        _identifiable_text_field(
            "shipper_address", turvo_inputs.pickup.address, pod_observations.get("shipper_address")
        ),
        _identifiable_text_field(
            "consignee_name", turvo_inputs.delivery.name, pod_observations.get("consignee_name")
        ),
        _identifiable_text_field(
            "consignee_address",
            turvo_inputs.delivery.address,
            pod_observations.get("consignee_address"),
        ),
    ]


def _normalize_reference(value: Any) -> str:
    return str(value or "").strip().casefold()


def _reference_id_matches(po_number: str, pod_observations: dict[str, Any]) -> bool:
    """Per-PO any-match: any POD-extracted number equals this PO's exact string (trim + casefold)."""
    extracted = pod_observations.get("extracted_reference_numbers") or []
    if not isinstance(extracted, list):
        return False
    target = _normalize_reference(po_number)
    return any(_normalize_reference(value) == target for value in extracted)


def _calendar_date_in_zone(iso_value: Any, time_zone: str | None) -> date | None:
    text = str(iso_value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if time_zone:
        try:
            parsed = parsed.astimezone(ZoneInfo(time_zone))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return parsed.date()


def _date_field(
    label: str,
    turvo_iso: str | None,
    pod_iso: Any,
    time_zone: str | None,
) -> PodFieldResult:
    """Award Pass 2 date points when POD and Turvo share the same calendar day in the stop TZ."""
    turvo_date = _calendar_date_in_zone(turvo_iso, time_zone)
    pod_date = _calendar_date_in_zone(pod_iso, time_zone)
    if turvo_date is not None and turvo_date == pod_date:
        return PodFieldResult(
            label=label,
            points_awarded=_PASS2_DATE_POINTS,
            points_possible=_PASS2_DATE_POINTS,
            remark=f"{label} matches Turvo ({turvo_date.isoformat()}).",
        )
    return PodFieldResult(
        label=label,
        points_awarded=0,
        points_possible=_PASS2_DATE_POINTS,
        remark=f"{label} does not match Turvo or is missing on POD.",
    )


def _tokens(value: str) -> set[str]:
    return {t.lower() for t in _IDENTIFIABLE_TOKEN_PATTERN.findall(value) if len(t) >= 3}


def _identifiable_text_field(
    label: str,
    turvo_value: str,
    pod_value: Any,
) -> PodFieldResult:
    """
    Award Pass 2 text points when POD text is non-blank and identifiable vs Turvo.

    Identifiable ≈ shares ≥1 significant token (len≥3) with Turvo, or Turvo has
    no comparable tokens (presence alone).
    """
    pod_text = str(pod_value or "").strip()
    if not pod_text:
        return PodFieldResult(
            label=label,
            points_awarded=0,
            points_possible=_PASS2_TEXT_POINTS,
            remark=f"{label} missing or blank on POD.",
        )
    turvo_tokens = _tokens(turvo_value or "")
    pod_tokens = _tokens(pod_text)
    identifiable = not turvo_tokens or bool(turvo_tokens & pod_tokens)
    if identifiable:
        return PodFieldResult(
            label=label,
            points_awarded=_PASS2_TEXT_POINTS,
            points_possible=_PASS2_TEXT_POINTS,
            remark=f"{label} present and identifiable on POD: '{pod_text}'.",
        )
    return PodFieldResult(
        label=label,
        points_awarded=0,
        points_possible=_PASS2_TEXT_POINTS,
        remark=f"{label} on POD ('{pod_text}') does not match Turvo ('{turvo_value}').",
    )


def _exceptions_from_observations(
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
) -> list[PodException]:
    exceptions: list[PodException] = []
    if pod_observations.get("damage_detected"):
        detail = str(pod_observations.get("damage_detail") or "").strip() or "Damage detected on POD."
        exceptions.append(PodException(exception_type="damage", detail=detail))

    pallets_shipped = pod_observations.get("pallets_shipped")
    ordered_qty = turvo_inputs.ordered_pallet_qty
    if isinstance(pallets_shipped, (int, float)) and isinstance(ordered_qty, (int, float)):
        if pallets_shipped < ordered_qty:
            exceptions.append(
                PodException(
                    exception_type="short_shipment",
                    detail=f"Expected {ordered_qty} pallets, received {pallets_shipped}.",
                )
            )
        elif pallets_shipped > ordered_qty:
            exceptions.append(
                PodException(
                    exception_type="over_shipment",
                    detail=f"Expected {ordered_qty} pallets, received {pallets_shipped}.",
                )
            )
    return exceptions
