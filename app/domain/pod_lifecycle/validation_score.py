"""Validation-bucket scoring strategies (pure; no I/O).

The 40-point shipment-validation bucket is split between Reference ID (up to 40,
split 20 pickup / 20 delivery, each prorated) and Pass 2 shipment attributes
(raw up to 40). Each strategy combines the two differently; only the active
strategy changes across the three prototype branches.

- ``fallback_swap``: Reference ID owns the bucket; Pass 2 replaces it only when
  the Reference ID score is 0.
- ``informational_pass2``: Reference ID alone decides the bucket; Pass 2 is
  scored and stored but contributes 0.
- ``blended_proration``: Reference ID keeps its earned points and Pass 2
  proportionally fills the remaining bucket capacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

VALIDATION_BUCKET_POINTS = 40

STRATEGY_FALLBACK_SWAP = "fallback_swap"
STRATEGY_INFORMATIONAL = "informational_pass2"
STRATEGY_BLENDED = "blended_proration"

# Each prototype branch sets its default strategy here.
DEFAULT_VALIDATION_STRATEGY = STRATEGY_BLENDED


@dataclass(frozen=True)
class ValidationBucketScore:
    """Outcome of the active strategy for the 40-point validation bucket."""

    strategy: str
    ref_id_score: int
    pass2_raw_score: int
    pass2_contribution: int
    score: int
    max_score: int = VALIDATION_BUCKET_POINTS


def _fallback_swap(ref_id_score: int, pass2_raw_score: int) -> int:
    """Reference ID owns the bucket unless it completely fails."""
    if ref_id_score == 0:
        return pass2_raw_score
    return ref_id_score


def _informational_pass2(ref_id_score: int, pass2_raw_score: int) -> int:
    """Only Reference ID decides the bucket; Pass 2 is informational."""
    return ref_id_score


def _blended_proration(ref_id_score: int, pass2_raw_score: int) -> int:
    """Pass 2 proportionally fills the remaining bucket capacity."""
    remaining = VALIDATION_BUCKET_POINTS - ref_id_score
    return ref_id_score + round(pass2_raw_score * remaining / VALIDATION_BUCKET_POINTS)


_STRATEGY_FUNCTIONS: dict[str, Callable[[int, int], int]] = {
    STRATEGY_FALLBACK_SWAP: _fallback_swap,
    STRATEGY_INFORMATIONAL: _informational_pass2,
    STRATEGY_BLENDED: _blended_proration,
}


def calculate_validation_score(
    ref_id_score: int,
    pass2_raw_score: int,
    strategy: str | None = None,
) -> ValidationBucketScore:
    """Combine Reference ID + Pass 2 raw scores using the active strategy."""
    strategy = strategy or DEFAULT_VALIDATION_STRATEGY
    try:
        combine = _STRATEGY_FUNCTIONS[strategy]
    except KeyError as exc:
        raise ValueError(f"unknown validation strategy: {strategy}") from exc
    bucket_score = combine(ref_id_score, pass2_raw_score)
    return ValidationBucketScore(
        strategy=strategy,
        ref_id_score=ref_id_score,
        pass2_raw_score=pass2_raw_score,
        pass2_contribution=max(0, bucket_score - ref_id_score),
        score=bucket_score,
    )
