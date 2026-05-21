"""Tests for the pgeocode state-name lookup wrapper.

These tests monkey-patch ``_get_nominatim`` so no actual GeoNames data is
downloaded; we never touch the network.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

import app.integrations.pgeocode.state_lookup as sl


class _FakeNomi:
    """Minimal stand-in for ``pgeocode.Nominatim`` for tests."""

    def __init__(self, value: object, place: str = "X") -> None:
        self._value = value
        self._place = place

    def query_postal_code(self, postal: str) -> pd.Series:
        return pd.Series({"state_name": self._value, "place_name": self._place})


def _patch_nomi(monkeypatch: pytest.MonkeyPatch, nomi: Any) -> None:
    monkeypatch.setattr(sl, "_get_nominatim", lambda iso2: nomi)


def test_lookup_state_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nomi(monkeypatch, _FakeNomi("Texas"))
    assert sl.lookup_state("U.S.A.", "76172") == "Texas"


def test_lookup_state_nan_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nomi(monkeypatch, _FakeNomi(math.nan))
    assert sl.lookup_state("U.S.A.", "00000") is None


def test_lookup_state_none_state_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nomi(monkeypatch, _FakeNomi(None))
    assert sl.lookup_state("U.S.A.", "12345") is None


def test_lookup_state_unsupported_country_returns_none() -> None:
    assert sl.lookup_state("Atlantis", "12345") is None


def test_lookup_state_missing_country_returns_none() -> None:
    assert sl.lookup_state(None, "12345") is None
    assert sl.lookup_state("", "12345") is None


def test_lookup_state_missing_postal_returns_none() -> None:
    assert sl.lookup_state("U.S.A.", None) is None
    assert sl.lookup_state("U.S.A.", "") is None
    assert sl.lookup_state("U.S.A.", "   ") is None


def test_lookup_state_handles_float_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nomi(monkeypatch, _FakeNomi("Iowa"))
    assert sl.lookup_state("U.S.A.", "51105.0") == "Iowa"


def test_lookup_state_handles_int_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nomi(monkeypatch, _FakeNomi("Iowa"))
    assert sl.lookup_state("U.S.A.", 51105) == "Iowa"


def test_lookup_state_strips_state_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nomi(monkeypatch, _FakeNomi("  Texas  "))
    assert sl.lookup_state("U.S.A.", "76172") == "Texas"


def test_lookup_state_swallows_pgeocode_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        def query_postal_code(self, _postal: str) -> pd.Series:
            raise RuntimeError("boom")

    _patch_nomi(monkeypatch, _Boom())
    assert sl.lookup_state("U.S.A.", "76172") is None


def test_lookup_state_returns_none_when_nominatim_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nomi(monkeypatch, None)
    assert sl.lookup_state("U.S.A.", "76172") is None
