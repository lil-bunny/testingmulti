"""Validation-bucket scoring (pure; no I/O).

The 40-point shipment-validation bucket is split between Reference ID (up to 40,
split 20 pickup / 20 delivery, each prorated) and Pass 2 shipment attributes
(raw up to 40). Reference ID keeps its earned points and Pass 2 proportionally
fills the remaining bucket capacity, so every validation signal contributes
while the bucket is hard-capped at 40.
"""

from __future__ import annotations

from dataclasses import dataclass

VALIDATION_BUCKET_POINTS = 40


@dataclass(frozen=True)
class ValidationBucketScore:
    """Outcome of the 40-point validation-bucket calculation."""

    ref_id_score: int
    pass2_raw_score: int
    pass2_contribution: int
    score: int
    max_score: int = VALIDATION_BUCKET_POINTS


def calculate_validation_score(ref_id_score: int, pass2_raw_score: int) -> ValidationBucketScore:
    """Combine Reference ID + Pass 2 raw scores.

    Reference ID keeps its earned points; Pass 2 proportionally fills the
    remaining bucket capacity (40 - Reference ID). The bucket never exceeds 40.
    """
    remaining = VALIDATION_BUCKET_POINTS - ref_id_score
    bucket_score = ref_id_score + round(pass2_raw_score * remaining / VALIDATION_BUCKET_POINTS)
    return ValidationBucketScore(
        ref_id_score=ref_id_score,
        pass2_raw_score=pass2_raw_score,
        pass2_contribution=max(0, bucket_score - ref_id_score),
        score=bucket_score,
    )
