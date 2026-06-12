"""Turvo Public API document list (outbound) — used for shipment-scoped POD checks.

GET /v1/documents/list with ``filter`` and ``context`` query params (JSON strings).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError
from app.services.turvo_oauth_service import TurvoOAuthService

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
        logger.info("POD document found for shipment_id=%s", sid)
        return _pod_check_result(
            success=True,
            shipment_id=sid,
            pod_exists=True,
            pod_documents=pod_docs,
            all_documents_count=len(documents_data),
            message="POD document found for shipment",
        )

    logger.info("No POD document found for shipment_id=%s", sid)
    return _pod_check_result(
        success=True,
        shipment_id=sid,
        pod_exists=False,
        pod_documents=[],
        all_documents_count=len(documents_data),
        message="No POD document found for this shipment",
    )


def shipment_display_number(shipment_payload: dict[str, Any]) -> str:
    """Turvo custom id for document naming (e.g. #30389)."""
    details = shipment_payload.get("details")
    if isinstance(details, dict):
        for key in ("customId", "custom_id", "id"):
            raw = details.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    return ""


def default_pod_document_name(shipment_id: str, shipment_payload: dict[str, Any] | None) -> str:
    display = shipment_display_number(shipment_payload or {})
    if display:
        return f"Proof of delivery - #{display}"
    return f"Proof of delivery - {shipment_id}"


def _upload_params(
    shipment_id: Any,
    *,
    document_name: str,
    lookup_id: str,
) -> dict[str, str]:
    context = {
        "id": _context_id_for_api(shipment_id),
        "type": "SHIPMENT",
    }
    attributes = {
        "name": document_name,
        "lookupId": lookup_id,
        "sharing": {"entities": []},
    }
    return {
        "fullResponse": "true",
        "context": json.dumps(context, separators=(",", ":")),
        "attributes": json.dumps(attributes, separators=(",", ":")),
    }


def parse_upload_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Turvo upload body to vendor-neutral document summary."""
    status = str(payload.get("Status", "")).upper()
    if status != "SUCCESS":
        return {
            "success": False,
            "message": f"Turvo upload returned Status={payload.get('Status')!r}",
            "document": None,
        }
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    doc_id = details.get("documentId") or details.get("id")
    doc_name = details.get("documentName") or details.get("name")
    doc_type = "proof_of_delivery"
    dt = details.get("documentType")
    if isinstance(dt, dict) and dt.get("value"):
        doc_type = str(dt["value"]).strip().lower().replace(" ", "_")
    return {
        "success": True,
        "message": "POD uploaded to TMS",
        "document": {
            "id": str(doc_id) if doc_id is not None else None,
            "name": str(doc_name) if doc_name is not None else None,
            "type": doc_type,
        },
        "raw_details": details,
    }


async def upload_pod_document(
    tenant_slug: str,
    shipment_id: Any,
    *,
    pdf_bytes: bytes,
    filename: str,
    document_name: str,
    lookup_id: str,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """POST /v1/documents with multipart ``attachment0``."""
    if not shipment_id:
        raise ValueError("shipment_id is required")
    slug = (tenant_slug or "").strip()
    if not slug:
        raise ValueError("tenant_slug is required")
    if not pdf_bytes:
        raise ValueError("pdf_bytes is required")
    lookup = (lookup_id or "").strip()
    if not lookup:
        raise ValueError("lookup_id is required")

    api = client or TurvoApiClient()
    params = _upload_params(
        shipment_id,
        document_name=document_name,
        lookup_id=lookup,
    )
    files = {
        "attachment0": (filename, pdf_bytes, "application/pdf"),
    }
    logger.info(
        "Uploading POD via Turvo POST /v1/documents shipment_id=%s filename=%s",
        shipment_id,
        filename,
    )
    payload = await api.request_multipart(
        slug,
        "POST",
        "/documents",
        params=params,
        files=files,
        timeout_s=settings.TURVO_POD_UPLOAD_TIMEOUT_S,
    )
    result = parse_upload_response(payload)
    result["shipment_id"] = str(shipment_id)
    return result


async def resolve_pod_lookup_id(tenant_slug: str) -> str:
    """Load ``pod_document_lookup_id`` from tenant TMS settings."""
    slug = (tenant_slug or "").strip()
    oauth = TurvoOAuthService()
    tms = oauth._load_tms(slug)
    lookup = (tms.pod_document_lookup_id or "").strip()
    if not lookup:
        raise TurvoApiError(
            f"Tenant {slug!r} missing tenants.settings.tms.pod_document_lookup_id",
            status_code=503,
        )
    return lookup
