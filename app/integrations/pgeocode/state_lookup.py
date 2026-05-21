"""Resolve a state name from (country_name, postal_code) using ``pgeocode``.

``pgeocode.Nominatim`` works offline against per-country GeoNames TSVs, which
are downloaded to the local cache on first construction. We cache one
``Nominatim`` instance per ISO2 code via :func:`functools.lru_cache` so that
the download cost is paid at most once per country per process.

Every failure mode here returns ``None`` (logged) so a flaky postal-code
lookup never breaks the surrounding tender ingest — the caller falls back
to ``state: ""``.
"""

from __future__ import annotations

import functools
import math
from typing import Optional

import pgeocode

from app.core.logger import get_logger
from app.integrations.pgeocode.country_aliases import get_country_iso

logger = get_logger(__name__)


@functools.lru_cache(maxsize=None)
def _get_nominatim(iso2: str) -> Optional["pgeocode.Nominatim"]:
    """Build (and cache) a ``pgeocode.Nominatim`` for one ISO2 country code.

    Returns ``None`` if the country is unsupported or the GeoNames data
    cannot be downloaded.
    """
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


def lookup_state(country_name: str | None, postal_code: object) -> str | None:
    """Return the GeoNames ``state_name`` for a (country, postal_code) pair.

    ``None`` is returned for any failure: unmapped country, blank postal code,
    pgeocode init failure, no postal match, or NaN result. This is intentional
    so the caller can fall back to ``state: ""`` without special-casing.
    """
    iso2 = get_country_iso(country_name)
    if iso2 is None:
        return None

    postal = _normalize_postal(postal_code)
    if postal is None:
        return None

    nomi = _get_nominatim(iso2)
    if nomi is None:
        return None

    try:
        row = nomi.query_postal_code(postal)
    except Exception:
        logger.warning(
            "pgeocode: query failed iso2=%s postal=%s",
            iso2,
            postal,
            exc_info=True,
        )
        return None

    state = row.get("state_name")
    if state is None:
        return None
    if isinstance(state, float) and math.isnan(state):
        return None
    s = str(state).strip()
    return s or None
