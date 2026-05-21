"""Tests for the sheet-country-name to ISO2 mapping."""

from __future__ import annotations

from app.integrations.pgeocode.country_aliases import (
    COUNTRY_TO_ISO,
    get_country_iso,
)


def test_known_aliases() -> None:
    assert get_country_iso("U.S.A.") == "US"
    assert get_country_iso("Canada") == "CA"
    assert get_country_iso("Germany") == "DE"
    assert get_country_iso("Great Britain") == "GB"
    assert get_country_iso("Pr of China") == "CN"
    assert get_country_iso("Taiwan R.O.C.") == "TW"
    assert get_country_iso("The Netherlands") == "NL"


def test_blank_and_unknown_yield_none() -> None:
    assert get_country_iso(None) is None
    assert get_country_iso("") is None
    assert get_country_iso("Unknown") is None
    assert get_country_iso("....") is None
    assert get_country_iso("Atlantis") is None


def test_whitespace_is_stripped() -> None:
    assert get_country_iso("  U.S.A.  ") == "US"
    assert get_country_iso("\tGermany\n") == "DE"


def test_dict_has_expected_size_and_iso2_values() -> None:
    assert len(COUNTRY_TO_ISO) == 62
    for name, code in COUNTRY_TO_ISO.items():
        assert isinstance(name, str) and name, f"bad key: {name!r}"
        assert isinstance(code, str) and len(code) == 2 and code.isupper(), (
            f"bad ISO2 for {name!r}: {code!r}"
        )
