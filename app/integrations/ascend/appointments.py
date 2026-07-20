"""Ascend appointment endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.ascend.errors import AscendApiError

_BASE_URL = "https://api.ascendcargo.com"
_DEFAULT_TIMEOUT_S = 60.0


def get_loc_ref_for_ascend_slots(
    *,
    reference_number: str,
    access_token: str,
    office_code: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> list[dict[str, Any]]:
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
            f"{_BASE_URL}/api/appointment/by-shipment/{ref}",
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend appointment fetch failed: {exc}") from exc
    if response.status_code >= 400:
        raise AscendApiError(
            "Ascend appointment fetch failed",
            status_code=response.status_code,
            body=response.text,
        )
    data = response.json()
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def update_appointment(
    *,
    appointment_id: str,
    body: dict[str, Any],
    access_token: str,
    office_code: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    appt_id = str(appointment_id or "").strip()
    if not appt_id:
        raise AscendApiError("appointment_id required")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if office_code:
        headers["Office-Code"] = office_code
    try:
        response = httpx.put(
            f"{_BASE_URL}/api/appointment/{appt_id}/update",
            headers=headers,
            json=body,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend appointment update failed: {exc}") from exc
    if response.status_code >= 400:
        raise AscendApiError(
            "Ascend appointment update failed",
            status_code=response.status_code,
            body=response.text,
        )
    data = response.json()
    return data if isinstance(data, dict) else {"result": data}
