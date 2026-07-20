"""Ascend shipment endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.ascend.errors import AscendApiError

_BASE_URL = "https://api.ascendcargo.com"
_DEFAULT_TIMEOUT_S = 60.0


def fetched_shipment_details(
    *,
    reference_number: str,
    access_token: str,
    office_code: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    ref = str(reference_number or "").strip()
    if not ref:
        raise AscendApiError("reference_number required")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    if office_code:
        headers["Office-Code"] = office_code
    try:
        response = httpx.get(
            f"{_BASE_URL}/api/shipments/detailed-shipment/{ref}",
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend shipment fetch failed: {exc}") from exc
    if response.status_code >= 400:
        raise AscendApiError(
            "Ascend shipment fetch failed",
            status_code=response.status_code,
            body=response.text,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise AscendApiError("Ascend shipment response is not JSON object")
    return data


def update_shipment_stops(
    *,
    reference_number: str,
    access_token: str,
    office_code: str,
    payload: dict[str, Any],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    ref = str(reference_number or "").strip()
    if not ref:
        raise AscendApiError("reference_number required")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if office_code:
        headers["Office-Code"] = office_code
    try:
        response = httpx.put(
            f"{_BASE_URL}/api/shipments/{ref}",
            headers=headers,
            json=payload,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend shipment update failed: {exc}") from exc
    if response.status_code >= 400:
        raise AscendApiError(
            "Ascend shipment update failed",
            status_code=response.status_code,
            body=response.text,
        )
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}
