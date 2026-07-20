"""Ascend warehouse slot availability."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.ascend.errors import AscendApiError

_BASE_URL = "https://api.ascendcargo.com/api/slots/warehouse-availability"
_DEFAULT_TIMEOUT_S = 60.0


def fetch_warehouse_availability(
    *,
    loc_id_ref: str,
    date_iso: str,
    office_code: str = "",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any] | list[Any] | None:
    loc = str(loc_id_ref or "").strip()
    date = str(date_iso or "").strip()
    if not loc or not date:
        return None
    headers: dict[str, str] = {"Accept": "application/json"}
    if office_code:
        headers["Office-Code"] = office_code.strip()
    try:
        response = httpx.get(
            _BASE_URL,
            params={"loc_id_ref": loc, "date": date},
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend availability fetch failed: {exc}") from exc
    if response.status_code >= 400:
        return None
    return response.json()
