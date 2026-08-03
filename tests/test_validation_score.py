"""Unit tests for the 40-point validation-bucket scoring."""

from __future__ import annotations

from app.domain.pod_lifecycle.validation_score import (
    VALIDATION_BUCKET_POINTS,
    calculate_validation_score,
)


def test_validation_keeps_reference_id_points() -> None:
    assert calculate_validation_score(20, 0).score == 20
    assert calculate_validation_score(40, 40).score == 40


def test_validation_fills_remaining_capacity() -> None:
    assert calculate_validation_score(20, 40).score == 40
    assert calculate_validation_score(20, 30).score == 35
    assert calculate_validation_score(20, 20).score == 30
    assert calculate_validation_score(0, 30).score == 30
    assert calculate_validation_score(0, 0).score == 0


def test_validation_never_exceeds_bucket() -> None:
    assert calculate_validation_score(30, 40).score <= VALIDATION_BUCKET_POINTS
    assert calculate_validation_score(10, 40).score == 40


def test_validation_tracks_contribution() -> None:
    result = calculate_validation_score(20, 30)
    assert result.score == 35
    assert result.pass2_contribution == 15
    assert result.ref_id_score == 20
    assert result.pass2_raw_score == 30
    assert result.max_score == VALIDATION_BUCKET_POINTS