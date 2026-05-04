"""Turvo tools — every workflow/agent entrypoint for this vendor lives in this module.

HTTP, OAuth, and webhooks stay in ``app.integrations.turvo``. Callers pass plain
arguments only (like ``tools.email``); workflow nodes read ``state.data`` and
call these functions. For another TMS, add e.g. ``app/tools/other_tms.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.documents import check_pod_by_shipment_id as check_pod_by_shipment_id_async
from app.integrations.turvo.shipments import get_shipment as get_shipment_async

logger = get_logger(__name__)

__all__ = (
    "check_pod_by_shipment_id",
    "get_shipment",
    "update_shipment",
    "upload_to_turvo",
)


def _stub_shipment(shipment_id: Any, error: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"shipment_id": str(shipment_id) if shipment_id else "", "convoy": False}
    if error:
        out["error"] = error
    return out


def _is_turvo_configured() -> bool:
    return bool(settings.TURVO_PUBLICAPI_URL)


def get_shipment(
    shipment_id: Any,
    app_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return Turvo shipment details for a given shipment id.

    ``app_user_id`` must be supplied by the caller when a live fetch is needed
    (nodes typically use ``state.data["app_user_id"]`` or env default).

    Falls back to a minimal stub when Turvo is not configured or ``app_user_id``
    is missing, so workflows remain testable without live Turvo creds.
    """
    if not shipment_id:
        return _stub_shipment(shipment_id)

    if not app_user_id or not _is_turvo_configured():
        logger.info(
            "Turvo not configured or app_user_id missing; returning stub shipment for %s",
            shipment_id,
        )
        return _stub_shipment(shipment_id)

    try:
        return asyncio.run(get_shipment_async(app_user_id, shipment_id))
    except TurvoApiError as e:
        logger.warning(
            "Turvo get_shipment failed for shipment_id=%s status=%s body=%s",
            shipment_id,
            e.status_code,
            e.body,
        )
        return _stub_shipment(shipment_id, error=str(e))
    except ValueError as e:
        logger.warning("Invalid Turvo get_shipment call: %s", e)
        return _stub_shipment(shipment_id, error=str(e))
    except Exception:
        logger.exception("Unexpected error fetching Turvo shipment %s", shipment_id)
        return _stub_shipment(shipment_id, error="unexpected_error")


def check_pod_by_shipment_id(
    shipment_id: Any,
    app_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return whether Turvo documents list includes proof of delivery for this shipment.

    Uses GET /v1/documents/list with a SHIPMENT context. When Turvo is
    not configured or ``app_user_id`` is missing, returns ``success: False`` with
    a clear message (no live call).
    """
    empty = {
        "success": False,
        "shipment_id": "",
        "pod_exists": False,
        "pod_documents": [],
        "all_documents_count": 0,
        "message": "shipment_id is required",
    }
    if not shipment_id:
        return empty

    sid = str(shipment_id)
    if not app_user_id or not _is_turvo_configured():
        logger.info(
            "Turvo not configured or app_user_id missing; skipping POD check for %s",
            sid,
        )
        return {
            "success": False,
            "shipment_id": sid,
            "pod_exists": False,
            "pod_documents": [],
            "all_documents_count": 0,
            "message": "Turvo not configured or app_user_id missing",
        }

    try:
        return asyncio.run(check_pod_by_shipment_id_async(app_user_id, shipment_id))
    except TurvoApiError as e:
        logger.warning(
            "Turvo check_pod_by_shipment_id failed shipment_id=%s status=%s body=%s",
            sid,
            e.status_code,
            e.body,
        )
        return {
            "success": False,
            "shipment_id": sid,
            "pod_exists": False,
            "pod_documents": [],
            "all_documents_count": 0,
            "message": f"Failed to check POD: {e}",
        }
    except ValueError as e:
        logger.warning("Invalid Turvo check_pod_by_shipment_id call: %s", e)
        return {
            "success": False,
            "shipment_id": sid,
            "pod_exists": False,
            "pod_documents": [],
            "all_documents_count": 0,
            "message": str(e),
        }
    except Exception:
        logger.exception("Unexpected error checking Turvo POD for %s", sid)
        return {
            "success": False,
            "shipment_id": sid,
            "pod_exists": False,
            "pod_documents": [],
            "all_documents_count": 0,
            "message": "Failed to check POD: unexpected_error",
        }


def update_shipment(data: dict[str, Any]) -> None:
    """Placeholder for Turvo shipment update; replace with real endpoint when wired."""
    logger.info("[SHIPMENT UPDATE] %s", data)


def upload_to_turvo(data: dict[str, Any]) -> None:
    """Push merged POD to Turvo for the shipment in ``data``.

    Workflow passes ``state.data`` (e.g. ``pod_merged_pdf_url``, ``shipment_id``).
    Document upload via Turvo Public API is not implemented yet; logs only.
    """
    shipment_id = data.get("shipment_id")
    merged = data.get("pod_merged_pdf_url")
    logger.info(
        "[TURVO POD UPLOAD] shipment_id=%s merged_url_present=%s (upload not wired)",
        shipment_id,
        bool(merged),
    )
