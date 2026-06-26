"""Resolve state from (country_name, postal_code) using ``pgeocode``.

Returns GeoNames ``state_code`` (e.g. ``IA``) when available, else ``state_name``.
"""

from __future__ import annotations

import functools
import math
import re
from typing import Any, Optional

import pgeocode

from app.core.logger import get_logger
from app.integrations.pgeocode.country_aliases import get_country_iso

logger = get_logger(__name__)


@functools.lru_cache(maxsize=None)
def _get_nominatim(iso2: str) -> Optional["pgeocode.Nominatim"]:
    """Build (and cache) a ``pgeocode.Nominatim`` for one ISO2 country code."""
    try:
        return pgeocode.Nominatim(iso2.lower())
    except Exception:
        logger.warning(
            "pgeocode: failed to init Nominatim for %s", iso2, exc_info=True
        )
        return None


def _normalize_postal(postal_code: object) -> str | None:
    """Coerce a sheet postal-code cell into a clean string, or ``None``."""
    if postal_code is None:
        return None
    s = str(postal_code).strip()
    if not s:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def _postal_query_candidates(postal_code: object) -> list[str]:
    """Postal strings to try with ``query_postal_code`` (full, then 5-digit US)."""
    base = _normalize_postal(postal_code)
    if base is None:
        return []
    candidates = [base]
    digits = re.sub(r"\D", "", base)
    if len(digits) >= 5:
        five = digits[:5]
        if five not in candidates:
            candidates.append(five)
    return candidates


def _series_field(row: Any, key: str) -> str | None:
    if row is None:
        return None
    val = row.get(key)
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return s or None


def lookup_state_display_name(
    country_name: str | None,
    postal_code: object,
    *,
    state_code_fallback: str | None = None,
) -> str | None:
    """Return full state name when pgeocode has it, else state code, else ``state_code_fallback``."""
    iso2 = get_country_iso(country_name)
    if iso2 is None:
        fb = (state_code_fallback or "").strip()
        return fb or None

    nomi = _get_nominatim(iso2)
    if nomi is None:
        fb = (state_code_fallback or "").strip()
        return fb or None

    for postal in _postal_query_candidates(postal_code):
        try:
            row = nomi.query_postal_code(postal)
        except Exception:
            logger.warning(
                "pgeocode: query failed iso2=%s postal=%s",
                iso2,
                postal,
                exc_info=True,
            )
            continue

        name = _series_field(row, "state_name")
        if name:
            return name
        code = _series_field(row, "state_code")
        if code:
            return code

    fb = (state_code_fallback or "").strip()
    return fb or None


def lookup_state(country_name: str | None, postal_code: object) -> str | None:
    """Return ``state_code`` (preferred) or ``state_name`` for (country, postal_code).

    ``None`` on any failure so callers can fall back to ``state: ""``.
    """
    iso2 = get_country_iso(country_name)
    if iso2 is None:
        return None

    nomi = _get_nominatim(iso2)
    if nomi is None:
        return None

    for postal in _postal_query_candidates(postal_code):
        try:
            row = nomi.query_postal_code(postal)
        except Exception:
            logger.warning(
                "pgeocode: query failed iso2=%s postal=%s",
                iso2,
                postal,
                exc_info=True,
            )
            continue

        code = _series_field(row, "state_code")
        if code:
            return code
        name = _series_field(row, "state_name")
        if name:
            return name

    return None


def _state_matches_row(row: Any, state: str) -> bool:
    state_norm = state.strip().lower()
    if not state_norm:
        return False
    code = _series_field(row, "state_code")
    if code and code.lower() == state_norm:
        return True
    name = _series_field(row, "state_name")
    if name and name.lower() == state_norm:
        return True
    return False


def lookup_postal(
    country_name: str | None,
    city: str | None,
    state: str | None,
) -> str | None:
    """Return a postal code for (country, city, state) when Turvo omits zip on globalRoute."""
    city_s = (city or "").strip()
    state_s = (state or "").strip()
    if not city_s or not state_s:
        return None

    iso2 = get_country_iso(country_name)
    if iso2 is None:
        return None

    nomi = _get_nominatim(iso2)
    if nomi is None:
        return None

    try:
        df = nomi.query_location(city_s)
    except Exception:
        logger.warning(
            "pgeocode: query_location failed iso2=%s city=%s",
            iso2,
            city_s,
            exc_info=True,
        )
        return None

    if df is None or getattr(df, "empty", True):
        return None

    try:
        for _, row in df.iterrows():
            if not _state_matches_row(row, state_s):
                continue
            postal = _series_field(row, "postal_code")
            if postal:
                return postal
    except Exception:
        logger.warning(
            "pgeocode: failed iterating location rows iso2=%s city=%s",
            iso2,
            city_s,
            exc_info=True,
        )
        return None

    return None
