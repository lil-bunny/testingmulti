"""
Map heterogeneous source row dicts (spreadsheet headers, API keys) to stable logical fields.

Match is case-insensitive and whitespace-stripped on both row keys and configured
candidates. First candidate that matches a row column wins.

Future: plug in fuzzy matching, locale-aware aliases, or ML-based column mapping without
changing callers if the ``project_row`` signature stays stable.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def normalize_header(label: str) -> str:
    return label.strip().lower()


def _normalized_key_index(row: dict[str, Any]) -> dict[str, str]:
    """First row key wins when two headers normalize to the same string."""
    out: dict[str, str] = {}
    for k in row:
        nk = normalize_header(str(k))
        if nk not in out:
            out[nk] = str(k)
    return out


def project_row(
    row: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """
    ``fields``: logical output key -> ordered list of candidate source column names.

    Missing columns become ``None``. Extra row keys are ignored unless listed as candidates.
    """
    index = _normalized_key_index(row)
    out: dict[str, Any] = {}
    for logical, candidates in fields.items():
        val: Any = None
        for cand in candidates:
            nk = normalize_header(str(cand))
            if nk in index:
                orig = index[nk]
                val = row.get(orig)
                break
        out[str(logical)] = val
    return out


def _cell_value_is_present(val: Any) -> bool:
    """True if a spreadsheet cell value should count as real data (not blank row)."""
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, float) and math.isnan(val):
        return False
    return True


def projected_row_has_any_value(row: Mapping[str, Any]) -> bool:
    """True when at least one projected field is non-null and not blank text."""
    return any(_cell_value_is_present(v) for v in row.values())


def drop_all_empty_projected_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove rows where every projected field is None or blank string."""
    return [r for r in rows if projected_row_has_any_value(r)]
