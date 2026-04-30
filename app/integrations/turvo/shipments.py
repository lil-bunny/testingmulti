"""Turvo Public API shipment endpoints.

Each function is a thin wrapper around ``TurvoApiClient`` (``public_api_client``) —
no auth/retry logic should live here.

Shipment-scoped POD checks use ``GET /v1/documents/list`` — see
``app.integrations.turvo.documents``.
"""

from __future__ import annotations

from typing import Any, Optional

from app.integrations.turvo.documents import check_pod_by_shipment_id
from app.integrations.turvo.public_api_client import TurvoApiClient


async def get_shipment(
    app_user_id: str,
    shipment_id: Any,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """GET /v1/shipments/{shipmentId} — full shipment details for the given id."""
    if not shipment_id:
        raise ValueError("shipment_id is required")
    if not app_user_id:
        raise ValueError("app_user_id is required")
    api = client or TurvoApiClient()
    return await api.request(
        app_user_id=app_user_id,
        method="GET",
        path=f"/shipments/{shipment_id}",
    )
