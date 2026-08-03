"""PoD-vs-Turvo scoring engine (pure; no DB/HTTP).

LLM supplies ``pod_observations``; this module applies the deterministic score.

Score model (stored):
- Flat field-wise scoring grouped by stop
- Signature inside delivery stop as identity field (0/60)
- reference_id per stop with comparisons[] (0/20 each)
- shipment_detail fields: dates (0/10), location/address (0/5) with source/target
- Root: finalScore, maxScore, passThreshold
- exceptions/remarks/reviewReasons/stopTimes omitted when empty

The final score uses blended proration (ref_id keeps points, pass2 fills
remaining capacity up to 40). This is computed here for storage but the
API layer owns the policy and can re-derive at read time.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.pod_lifecycle.pod_score_result import (
    PASS_THRESHOLD,
    PoComparison,
    PodException,
    PodScoreResult,
    ScoredField,
    StopScore,
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
from app.integrations.turvo.pod_inputs import (  # noqa: TC001
    TurvoPurchaseOrder,
    TurvoShipmentPodInputs,
)

_IDENTIFIABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_REFUSED_DELIVERY_PATTERN = re.compile(r"\brefus(?:e|ed|al)\b", re.IGNORECASE)

_VALIDATION_BUCKET_MAX = 40


def score_pod(
    pod_observations: dict[str, Any],
    turvo_inputs: TurvoShipmentPodInputs,
) -> PodScoreResult:
    """Score a PoD against Turvo shipment inputs. Pure and deterministic."""
    exceptions = _exceptions_from_observations(pod_observations, turvo_inputs)

    if not turvo_inputs.purchase_orders:
        return PodScoreResult(
            final_score=0,
            max_score=100,
            pass_threshold=PASS_THRESHOLD,
            stops=[],
            remarks=[REMARK_NO_TURVO_PO],
            review_reasons=[REMARK_NO_TURVO_PO],
            exceptions=exceptions or None,
            needs_action=True,
        )

    pickup_stop = _build_stop(STOP_TYPE_PICKUP, 1, turvo_inputs, pod_observations)
    delivery_stop = _build_stop(STOP_TYPE_DELIVERY, 2, turvo_inputs, pod_observations)

    # Compute final score using blended proration
    ref_id_total = _sum_identity_scores([pickup_stop, delivery_stop], exclude_signature=True)
    signature_score = _get_signature_score(delivery_stop)
    detail_raw = _sum_shipment_detail_scores([pickup_stop, delivery_stop])

    remaining = _VALIDATION_BUCKET_MAX - ref_id_total
    detail_contribution = round(detail_raw * remaining / _VALIDATION_BUCKET_MAX) if _VALIDATION_BUCKET_MAX else 0
    validation_bucket = ref_id_total + detail_contribution
    final_score = min(100, signature_score + validation_bucket)

    review_reasons = _delivery_review_reasons(pod_observations.get("review_reasons"))
    remarks: list[str] = []

    return PodScoreResult(
        final_score=final_score,
        max_score=100,
        pass_threshold=PASS_THRESHOLD,
        stops=[pickup_stop, delivery_stop],
        exceptions=exceptions or None,
        remarks=remarks or None,
        review_reasons=review_reasons or None,
        needs_action=True,
    )


def _build_stop(
    stop_type: str,
    stop_order: int,
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> StopScore:
    """Build all fields for a single stop."""
    fields: list[ScoredField] = []

    # Signature only on delivery
    if stop_type == STOP_TYPE_DELIVERY:
        fields.append(_signature_field(pod_observations))

    # Reference ID
    fields.append(_reference_id_field(stop_type, turvo_inputs, pod_observations))

    # Shipment detail fields
    fields.extend(_shipment_detail_fields(stop_type, turvo_inputs, pod_observations))

    stop_times = list(pod_observations.get("stop_times") or [])

    return StopScore(
        stop_type=stop_type,
        stop_order=stop_order,
        fields=fields,
        stop_times=stop_times or None,
    )


def _signature_field(pod_observations: dict[str, Any]) -> ScoredField:
    present = bool(pod_observations.get("delivery_signature_present"))
    return ScoredField(
        label=LABEL_SIGNATURE,
        category="identity",
        score=SIGNATURE_POINTS if present else 0,
        max_score=SIGNATURE_POINTS,
        remark=REMARK_SIGNATURE_PRESENT if present else REMARK_SIGNATURE_ABSENT,
    )


def _reference_id_field(
    stop_type: str,
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> ScoredField:
    pos = [po for po in turvo_inputs.purchase_orders if po.stop_type == stop_type]
    total = len(pos)

    if total == 0:
        return ScoredField(
            label=LABEL_REFERENCE_ID,
            category="identity",
            score=0,
            max_score=REFERENCE_ID_POINTS_PER_STOP,
            remark=REMARK_REFERENCE_ID_NO_POS_TEMPLATE.format(stop_type=stop_type),
            comparisons=[],
        )

    comparisons = []
    matched_count = 0
    for po in pos:
        match_data = _po_stop_match(po.po_number, pod_observations)
        is_matched = bool(match_data.get("reference_and_stop_match"))
        if is_matched:
            matched_count += 1
        comparisons.append(
            PoComparison(
                po_number=po.po_number,
                matched=is_matched,
                source=po.po_number if is_matched else None,
                target=po.po_number,
            )
        )

    score = round(REFERENCE_ID_POINTS_PER_STOP * matched_count / total)
    if matched_count:
        remark = REMARK_REFERENCE_ID_MATCH_TEMPLATE.format(
            stop_type=stop_type, matched=matched_count, total=total
        )
    else:
        remark = REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE.format(stop_type=stop_type)

    return ScoredField(
        label=LABEL_REFERENCE_ID,
        category="identity",
        score=score,
        max_score=REFERENCE_ID_POINTS_PER_STOP,
        remark=remark,
        comparisons=comparisons,
    )


def _shipment_detail_fields(
    stop_type: str,
    turvo_inputs: TurvoShipmentPodInputs,
    pod_observations: dict[str, Any],
) -> list[ScoredField]:
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
                "delivery_location",
                turvo_inputs.delivery.name,
                pod_observations.get("delivery_location"),
                None,
                False,
            ),
            (
                "delivery_address",
                turvo_inputs.delivery.address,
                pod_observations.get("delivery_address"),
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


def _sum_identity_scores(stops: list[StopScore], *, exclude_signature: bool = False) -> int:
    total = 0
    for stop in stops:
        for f in stop.fields:
            if f.category == "identity":
                if exclude_signature and f.label == LABEL_SIGNATURE:
                    continue
                total += f.score
    return total


def _get_signature_score(delivery_stop: StopScore) -> int:
    for f in delivery_stop.fields:
        if f.label == LABEL_SIGNATURE:
            return f.score
    return 0


def _sum_shipment_detail_scores(stops: list[StopScore]) -> int:
    return sum(
        f.score for stop in stops for f in stop.fields if f.category == "shipment_detail"
    )


def _delivery_review_reasons(raw_reasons: object) -> list[str]:
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason) for reason in raw_reasons if "pickup" not in str(reason).casefold()]


def _po_stop_match(po_number: str, pod_observations: dict[str, Any]) -> dict[str, Any]:
    matches = pod_observations.get("po_matches")
    if isinstance(matches, dict):
        value = matches.get(po_number)
        if isinstance(value, dict):
            return value

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
) -> ScoredField:
    turvo_date = _calendar_date_in_zone(target, time_zone)
    pod_date = _calendar_date_in_zone(source, time_zone)
    if turvo_date is not None and turvo_date == pod_date:
        return ScoredField(
            label=label,
            category="shipment_detail",
            score=DATE_POINTS,
            max_score=DATE_POINTS,
            remark=REMARK_DATE_MATCH_TEMPLATE.format(
                label=label, turvo_date=turvo_date.isoformat()
            ),
            target=target,
            source=_clean_iso_text(source),
        )
    return ScoredField(
        label=label,
        category="shipment_detail",
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
) -> ScoredField:
    pod_text = str(source or "").strip()
    if not pod_text:
        return ScoredField(
            label=label,
            category="shipment_detail",
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
        return ScoredField(
            label=label,
            category="shipment_detail",
            score=TEXT_POINTS,
            max_score=TEXT_POINTS,
            remark=REMARK_TEXT_IDENTIFIABLE_TEMPLATE.format(label=label, pod_text=pod_text),
            target=target or None,
            source=pod_text,
        )
    return ScoredField(
        label=label,
        category="shipment_detail",
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
