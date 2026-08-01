"""PoD-vs-Turvo scoring engine (pure; no DB/HTTP).

LLM supplies ``pod_observations``; this module applies the deterministic score.

Score model:
- ``signature``: document-level delivery receiver proof shared across POs (0/60)
- ``reference_id`` per stop (pickup / delivery): up to 20 each, prorated by the
  ratio of matched Turvo POs on that stop
- Pass 2 ``diff`` fields (dates + shipper/consignee text) are always computed,
  scored, and stored with both Turvo and POD values (0/40 raw)
- ``validation``: the 40-point bucket combines reference-id + Pass 2 via the
  active strategy from ``validation_score`` (fallback_swap / informational_pass2
  / blended_proration), driven by the per-branch default.

The final score is signature + validation bucket, always out of 100. Exceptions
never change points.
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
    PodStopScore,
    StopType,
)
from app.domain.pod_lifecycle.scoring_constants import (
    DATE_POINTS,
    EXCEPTION_DAMAGE_DEFAULT_DETAIL,
    EXCEPTION_PALLET_QTY_TEMPLATE,
    LABEL_REFERENCE_ID,
    LABEL_SIGNATURE,
    REFERENCE_ID_POINTS_PER_STOP,
    REMARK_DATE_MATCH_TEMPLATE,
    REMARK_DATE_NO_MATCH_TEMPLATE,
    REMARK_NO_TURVO_PO,
    REMARK_REFERENCE_ID_MATCH_TEMPLATE,
    REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE,
    REMARK_REFERENCE_ID_NO_POS_TEMPLATE,
    REMARK_SIGNATURE_ABSENT,
    REMARK_SIGNATURE_PRESENT,
    REMARK_TEXT_IDENTIFIABLE_TEMPLATE,
    REMARK_TEXT_MISSING_TEMPLATE,
    REMARK_TEXT_NO_MATCH_TEMPLATE,
    SIGNATURE_POINTS,
    STOP_TYPE_DELIVERY,
    STOP_TYPE_PICKUP,
    TEXT_POINTS,
)
from app.domain.pod_lifecycle.validation_score import calculate_validation_score
from app.integrations.turvo.pod_inputs import (  # noqa: TC001
    TurvoPurchaseOrder,
    TurvoShipmentPodInputs,
)

_IDENTIFIABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_REFUSED_DELIVERY_PATTERN = re.compile(r"\brefus(?:e|ed|al)\b", re.IGNORECASE)


def score_pod(
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
    strategy: str | None = None,
) -> PodScoreResult:
    """
    Score a PoD against Turvo shipment inputs. Pure and deterministic.

    ``strategy`` selects the 40-point validation-bucket combination; it defaults
    to ``validation_score.DEFAULT_VALIDATION_STRATEGY``. The numeric score has an
    informational PASS/FAIL status at ``PASS_THRESHOLD``. Every scored POD
    still routes to manual review.
    """
    exceptions = _exceptions_from_observations(pod_observations, turvo_inputs)
    remarks: list[str] = []

    if not turvo_inputs.purchase_orders:
        remarks.append(REMARK_NO_TURVO_PO)
        return PodScoreResult(
            signature=_signature_field(pod_observations),
            stops=[],
            validation=calculate_validation_score(0, 0, strategy),
            final_score=0,
            overall_status="FAIL",
            pass_threshold=PASS_THRESHOLD,
            exceptions=exceptions,
            needs_action=True,
            remarks=remarks,
            review_reasons=[REMARK_NO_TURVO_PO],
        )

    signature = _signature_field(pod_observations)
    stops = [
        _score_stop(stop_type, turvo_inputs, pod_observations)
        for stop_type in (STOP_TYPE_PICKUP, STOP_TYPE_DELIVERY)
    ]
    po_scores = [_score_po(po, pod_observations) for po in turvo_inputs.purchase_orders]

    ref_id_total = sum(stop.reference_id.score for stop in stops)
    pass2_raw = sum(field.score for stop in stops for field in stop.diff)
    validation = calculate_validation_score(ref_id_total, pass2_raw, strategy)

    final_score = min(100, signature.score + validation.score)
    review_reasons = _delivery_review_reasons(pod_observations.get("review_reasons"))
    # Every scored POD routes to Ops review; concrete reasons stay visible in
    # exceptions and review_reasons.
    needs_action = True
    overall_status = "PASS" if final_score >= PASS_THRESHOLD else "FAIL"

    return PodScoreResult(
        signature=signature,
        stops=stops,
        validation=validation,
        final_score=final_score,
        overall_status=overall_status,
        pass_threshold=PASS_THRESHOLD,
        po_scores=po_scores,
        exceptions=exceptions,
        needs_action=needs_action,
        remarks=remarks,
        review_reasons=review_reasons,
        stop_times=list(pod_observations.get("stop_times") or []),
    )


def _delivery_review_reasons(raw_reasons: object) -> list[str]:
    """Keep review reasons relevant to the score-bearing delivery stop."""
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason) for reason in raw_reasons if "pickup" not in str(reason).casefold()]


def _signature_field(pod_observations: dict[str, Any]) -> PodFieldResult:
    """Document-level delivery receiver proof, shared across every PO."""
    present = bool(pod_observations.get("delivery_signature_present"))
    return PodFieldResult(
        label=LABEL_SIGNATURE,
        score=SIGNATURE_POINTS if present else 0,
        max_score=SIGNATURE_POINTS,
        remark=REMARK_SIGNATURE_PRESENT if present else REMARK_SIGNATURE_ABSENT,
    )


def _score_stop(
    stop_type: StopType,
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> PodStopScore:
    """Score one stop's reference-id (prorated) and always-scored diff fields."""
    pos = [po for po in turvo_inputs.purchase_orders if po.stop_type == stop_type]
    total = len(pos)
    matched = sum(
        1
        for po in pos
        if _po_stop_match(po.po_number, pod_observations).get("reference_and_stop_match")
    )
    return PodStopScore(
        stop_type=stop_type,
        po_total=total,
        po_matched=matched,
        reference_id=_reference_id_field(stop_type, total, matched),
        diff=_diff_fields(stop_type, turvo_inputs, pod_observations),
    )


def _reference_id_field(stop_type: StopType, total: int, matched: int) -> PodFieldResult:
    if total == 0:
        return PodFieldResult(
            label=LABEL_REFERENCE_ID,
            score=0,
            max_score=REFERENCE_ID_POINTS_PER_STOP,
            remark=REMARK_REFERENCE_ID_NO_POS_TEMPLATE.format(stop_type=stop_type),
        )
    score = round(REFERENCE_ID_POINTS_PER_STOP * matched / total)
    if matched:
        remark = REMARK_REFERENCE_ID_MATCH_TEMPLATE.format(
            stop_type=stop_type, matched=matched, total=total
        )
    else:
        remark = REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE.format(stop_type=stop_type)
    return PodFieldResult(
        label=LABEL_REFERENCE_ID,
        score=score,
        max_score=REFERENCE_ID_POINTS_PER_STOP,
        remark=remark,
    )


def _score_po(
    po: TurvoPurchaseOrder,
    pod_observations: dict[str, Any],
) -> PodPurchaseOrderScore:
    """Per-Turvo-PO audit evidence: matched flag + page comparisons."""
    po_match = _po_stop_match(po.po_number, pod_observations)
    return PodPurchaseOrderScore(
        po_number=po.po_number,
        stop_type=po.stop_type,
        matched=bool(po_match.get("reference_and_stop_match")),
        page_comparisons=list(po_match.get("page_comparisons") or []),
    )


def _diff_fields(
    stop_type: StopType,
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> list[PodFieldResult]:
    if stop_type == STOP_TYPE_PICKUP:
        specs = (
            (
                "pickup_date",
                turvo_inputs.pickup_date,
                pod_observations.get("pickup_date"),
                turvo_inputs.pickup.time_zone,
                True,
            ),
            (
                "pickup_location",
                turvo_inputs.pickup.name,
                pod_observations.get("pickup_location"),
                None,
                False,
            ),
            (
                "pickup_address",
                turvo_inputs.pickup.address,
                pod_observations.get("pickup_address"),
                None,
                False,
            ),
        )
    else:
        specs = (
            (
                "delivery_date",
                turvo_inputs.delivery_date,
                pod_observations.get("delivery_date"),
                turvo_inputs.delivery.time_zone,
                True,
            ),
            (
                "destination_location",
                turvo_inputs.delivery.name,
                pod_observations.get("destination_location"),
                None,
                False,
            ),
            (
                "destination_address",
                turvo_inputs.delivery.address,
                pod_observations.get("destination_address"),
                None,
                False,
            ),
        )
    return [
        _date_field(label, target, source, time_zone)
        if is_date
        else _identifiable_text_field(label, target or "", source)
        for label, target, source, time_zone, is_date in specs
    ]


def _po_stop_match(po_number: str, pod_observations: dict[str, Any]) -> dict[str, Any]:
    """Return the accumulated page evidence for a PO's Turvo-owned stop."""
    matches = pod_observations.get("po_matches")
    if isinstance(matches, dict):
        value = matches.get(po_number)
        if isinstance(value, dict):
            return value

    # Compatibility for pre-stop-aware extracts. New POD analyses always use the
    # page-level match above; historical/unit callers may only have a flat list.
    references = pod_observations.get("extracted_reference_numbers")
    if isinstance(references, list) and any(
        str(value or "").strip().casefold() == po_number.strip().casefold()
        for value in references
    ):
        return {"reference_and_stop_match": True}
    return {}


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
    target: str | None,
    source: Any,
    time_zone: str | None,
) -> PodFieldResult:
    """Award date points when POD and Turvo share the same calendar day in the stop TZ."""
    turvo_date = _calendar_date_in_zone(target, time_zone)
    pod_date = _calendar_date_in_zone(source, time_zone)
    if turvo_date is not None and turvo_date == pod_date:
        return PodFieldResult(
            label=label,
            score=DATE_POINTS,
            max_score=DATE_POINTS,
            remark=REMARK_DATE_MATCH_TEMPLATE.format(
                label=label, turvo_date=turvo_date.isoformat()
            ),
            target=target,
            source=_clean_iso_text(source),
        )
    return PodFieldResult(
        label=label,
        score=0,
        max_score=DATE_POINTS,
        remark=REMARK_DATE_NO_MATCH_TEMPLATE.format(label=label),
        target=target,
        source=_clean_iso_text(source),
    )


def _clean_iso_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _tokens(value: str) -> set[str]:
    return {t.lower() for t in _IDENTIFIABLE_TOKEN_PATTERN.findall(value) if len(t) >= 3}


def _identifiable_text_field(
    label: str,
    target: str,
    source: Any,
) -> PodFieldResult:
    """
    Award text points when POD text is non-blank and identifiable vs Turvo.

    Identifiable ≈ shares ≥1 significant token (len≥3) with Turvo, or Turvo has
    no comparable tokens (presence alone).
    """
    pod_text = str(source or "").strip()
    if not pod_text:
        return PodFieldResult(
            label=label,
            score=0,
            max_score=TEXT_POINTS,
            remark=REMARK_TEXT_MISSING_TEMPLATE.format(label=label),
            target=target or None,
            source=None,
        )
    turvo_tokens = _tokens(target or "")
    pod_tokens = _tokens(pod_text)
    identifiable = not turvo_tokens or bool(turvo_tokens & pod_tokens)
    if identifiable:
        return PodFieldResult(
            label=label,
            score=TEXT_POINTS,
            max_score=TEXT_POINTS,
            remark=REMARK_TEXT_IDENTIFIABLE_TEMPLATE.format(label=label, pod_text=pod_text),
            target=target or None,
            source=pod_text,
        )
    return PodFieldResult(
        label=label,
        score=0,
        max_score=TEXT_POINTS,
        remark=REMARK_TEXT_NO_MATCH_TEMPLATE.format(
            label=label, pod_text=pod_text, target=target
        ),
        target=target or None,
        source=pod_text,
    )


def _exceptions_from_observations(
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
) -> list[PodException]:
    exceptions: list[PodException] = []
    if pod_observations.get("damage_detected"):
        detail = (
            str(pod_observations.get("damage_detail") or "").strip()
            or EXCEPTION_DAMAGE_DEFAULT_DETAIL
        )
        exception_type = (
            "refused_delivery"
            if pod_observations.get("refused_delivery") or _REFUSED_DELIVERY_PATTERN.search(detail)
            else "damage"
        )
        exceptions.append(PodException(exception_type=exception_type, detail=detail))

    pallets_shipped = pod_observations.get("pallets_shipped")
    ordered_qty = turvo_inputs.ordered_pallet_qty
    if isinstance(pallets_shipped, (int, float)) and isinstance(ordered_qty, (int, float)):
        if pallets_shipped < ordered_qty:
            exceptions.append(
                PodException(
                    exception_type="short_shipment",
                    detail=EXCEPTION_PALLET_QTY_TEMPLATE.format(
                        ordered_qty=ordered_qty, pallets_shipped=pallets_shipped
                    ),
                )
            )
        elif pallets_shipped > ordered_qty:
            exceptions.append(
                PodException(
                    exception_type="over_shipment",
                    detail=EXCEPTION_PALLET_QTY_TEMPLATE.format(
                        ordered_qty=ordered_qty, pallets_shipped=pallets_shipped
                    ),
                )
            )
    return exceptions
