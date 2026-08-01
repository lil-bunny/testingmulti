"""Unit tests for the 40-point validation-bucket strategies."""

from __future__ import annotations

import pytest

from app.domain.pod_lifecycle.validation_score import (
    STRATEGY_BLENDED,
    STRATEGY_FALLBACK_SWAP,
    STRATEGY_INFORMATIONAL,
    VALIDATION_BUCKET_POINTS,
    calculate_validation_score,
)


def test_fallback_swap_reference_id_owns_bucket() -> None:
    assert calculate_validation_score(30, 40, strategy=STRATEGY_FALLBACK_SWAP).score == 30
    assert calculate_validation_score(20, 40, strategy=STRATEGY_FALLBACK_SWAP).score == 20


def test_fallback_swap_pass2_swaps_in_only_on_zero_ref() -> None:
    assert calculate_validation_score(0, 30, strategy=STRATEGY_FALLBACK_SWAP).score == 30
    assert calculate_validation_score(0, 0, strategy=STRATEGY_FALLBACK_SWAP).score == 0


def test_informational_pass2_ignores_pass2() -> None:
    assert calculate_validation_score(30, 40, strategy=STRATEGY_INFORMATIONAL).score == 30
    assert calculate_validation_score(0, 30, strategy=STRATEGY_INFORMATIONAL).score == 0
    assert calculate_validation_score(20, 20, strategy=STRATEGY_INFORMATIONAL).score == 20


def test_blended_proration_fills_remaining_capacity() -> None:
    assert calculate_validation_score(40, 40, strategy=STRATEGY_BLENDED).score == 40
    assert calculate_validation_score(20, 40, strategy=STRATEGY_BLENDED).score == 40
    assert calculate_validation_score(20, 30, strategy=STRATEGY_BLENDED).score == 35
    assert calculate_validation_score(20, 20, strategy=STRATEGY_BLENDED).score == 30
    assert calculate_validation_score(0, 30, strategy=STRATEGY_BLENDED).score == 30
    assert calculate_validation_score(0, 0, strategy=STRATEGY_BLENDED).score == 0


def test_blended_proration_never_exceeds_bucket() -> None:
    assert calculate_validation_score(30, 40, strategy=STRATEGY_BLENDED).score <= VALIDATION_BUCKET_POINTS
    assert calculate_validation_score(10, 40, strategy=STRATEGY_BLENDED).score == 40


def test_calculate_validation_score_dispatches_and_tracks_contribution() -> None:
    result = calculate_validation_score(20, 30, strategy=STRATEGY_BLENDED)
    assert result.score == 35
    assert result.pass2_contribution == 15
    assert result.ref_id_score == 20
    assert result.pass2_raw_score == 30
    assert result.max_score == VALIDATION_BUCKET_POINTS

    fallback = calculate_validation_score(0, 30, strategy=STRATEGY_FALLBACK_SWAP)
    assert fallback.score == 30
    assert fallback.pass2_contribution == 30

    informational = calculate_validation_score(30, 40, strategy=STRATEGY_INFORMATIONAL)
    assert informational.pass2_contribution == 0


def test_unknown_strategy_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown validation strategy"):
        calculate_validation_score(20, 20, strategy="no_such_strategy")


def test_default_strategy_resolves_without_error() -> None:
    result = calculate_validation_score(20, 20)
    assert result.score == result.ref_id_score + result.pass2_contribution
    assert result.score <= VALIDATION_BUCKET_POINTS


def test_default_strategy_is_a_registered_strategy() -> None:
    from app.domain.pod_lifecycle import validation_score as module

    assert module.DEFAULT_VALIDATION_STRATEGY in module._STRATEGY_FUNCTIONS  # noqa: SLF001


def test_default_strategy_is_blended_proration() -> None:
    from app.domain.pod_lifecycle import validation_score as module

    assert module.DEFAULT_VALIDATION_STRATEGY == STRATEGY_BLENDED
    assert calculate_validation_score(20, 30).score == 35
    assert calculate_validation_score(0, 30).score == 30
