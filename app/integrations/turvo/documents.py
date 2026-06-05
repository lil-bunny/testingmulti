"""Turvo Public API document list (outbound) — used for shipment-scoped POD checks.

GET /v1/documents/list with ``filter`` and ``context`` query params (JSON strings).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.core.logger import get_logger
from app.integrations.turvo.public_api_client import TurvoApiClient

logger = get_logger(__name__)

_DEFAULT_LIST_FILTER: dict[str, Any] = {"pageSize": 24, "start": 0}

# Turvo returns documentType.value e.g. "Proof of delivery"; match case-insensitively.
_PROOF_OF_DELIVERY_VALUE = "proof of delivery"


def _context_id_for_api(shipment_id: Any) -> Any:
    s = str(shipment_id).strip()
    if s.isdigit():
        return int(s)
    return shipment_id


def _documents_list_params(shipment_id: Any) -> dict[str, str]:
    context = {
        "id": _context_id_for_api(shipment_id),
        "type": "SHIPMENT",
    }
    return {
        "filter": json.dumps(_DEFAULT_LIST_FILTER, separators=(",", ":")),
        "context": json.dumps(context, separators=(",", ":")),
    }


def _document_list_item_is_pod(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    dt = doc.get("documentType")
    if not isinstance(dt, dict):
        return False
    val = str(dt.get("value", "")).strip().lower()
    return val == _PROOF_OF_DELIVERY_VALUE


def _pod_check_result(
    *,
    success: bool,
    shipment_id: str,
    pod_exists: bool,
    pod_documents: list[dict[str, Any]],
    all_documents_count: int,
    message: str,
) -> dict[str, Any]:
    return {
        "success": success,
        "shipment_id": shipment_id,
        "pod_exists": pod_exists,
        "pod_documents": pod_documents,
        "all_documents_count": all_documents_count,
        "message": message,
    }


async def list_documents_for_shipment(
    tenant_slug: str,
    shipment_id: Any,
    *,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """GET /v1/documents/list?filter=...&context=... — raw Turvo JSON body."""
    if not shipment_id:
        raise ValueError("shipment_id is required")
    slug = (tenant_slug or "").strip()
    if not slug:
        raise ValueError("tenant_slug is required")
    api = client or TurvoApiClient()
    return await api.request(
        slug,
        "GET",
        "/documents/list",
        params=_documents_list_params(shipment_id),
    )


async def check_pod_by_shipment_id(
    tenant_slug: str,
    shipment_id: Any,
    *,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """Use documents list API; POD = any row with ``documentType.value`` proof of delivery."""
    if not shipment_id:
        raise ValueError("shipment_id is required")
    slug = (tenant_slug or "").strip()
    if not slug:
        raise ValueError("tenant_slug is required")

    sid = str(shipment_id)
    logger.info("Checking POD via Turvo GET /v1/documents/list shipment_id=%s", sid)

    payload = await list_documents_for_shipment(
        slug,
        shipment_id,
        client=client,
    )

    status = str(payload.get("Status", "")).upper()
    if status != "SUCCESS":
        logger.warning(
            "Turvo documents/list non-success shipment_id=%s Status=%s",
            sid,
            payload.get("Status"),
        )
        return _pod_check_result(
            success=False,
            shipment_id=sid,
            pod_exists=False,
            pod_documents=[],
            all_documents_count=0,
            message=f"Turvo documents list returned Status={payload.get('Status')!r}",
        )

    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    documents_data = details.get("documents") if details else None
    if not isinstance(documents_data, list):
        documents_data = []

    pod_docs = [d for d in documents_data if _document_list_item_is_pod(d)]
    pod_exists = len(pod_docs) > 0

    if pod_exists:
        logger.info(
            "POD documents found (documents/list) shipment_id=%s pod_count=%s total_docs=%s",
            sid,
            len(pod_docs),
            len(documents_data),
        )
        return _pod_check_result(
            success=True,
            shipment_id=sid,
            pod_exists=True,
            pod_documents=pod_docs,
            all_documents_count=len(documents_data),
            message=f"POD found ({len(pod_docs)} document(s))",
        )

    logger.info(
        "No POD documents found (documents/list) shipment_id=%s total_docs=%s",
        sid,
        len(documents_data),
    )
    return _pod_check_result(
        success=True,
        shipment_id=sid,
        pod_exists=False,
        pod_documents=[],
        all_documents_count=len(documents_data),
        message="No POD document found for this shipment",
    )
