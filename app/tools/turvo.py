"""Turvo tools — every workflow/agent entrypoint for this vendor lives in this module.

HTTP, OAuth, and webhooks stay in ``app.integrations.turvo``. Callers pass plain
arguments only (like ``tools.email``); workflow nodes read ``state.data`` and
call these functions. For another TMS, add e.g. ``app/tools/other_tms.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.domain.tms.connection_failure import is_tms_connection_timeout
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.documents import (
    check_pod_by_shipment_id as check_pod_by_shipment_id_async,
    default_pod_document_name,
    resolve_pod_lookup_id,
    upload_pod_document,
)
from app.integrations.turvo.load_to_shipment import (
    load_id_to_shipment_id_async,
)
from app.integrations.turvo.shipments import get_shipment as get_shipment_async
from app.services.pod_lifecycle.pdf_optimizer import (
    PodPdfOptimizeError,
    optimize_for_tms_upload,
)
from app.tools.pdf_raster import PdfTooLargeError
from app.services.s3bucket_service import bucket
from app.tools.documents import resolve_merged_pod_object_key
from app.workflows.shipment_resolver import resolve_shipment_id

logger = get_logger(__name__)

__all__ = (
    "check_pod_by_shipment_id",
    "get_shipment",
    "load_id_to_shipment_id",
    "update_shipment",
    "upload_to_turvo",
)


def _stub_shipment(shipment_id: Any, error: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"shipment_id": str(shipment_id) if shipment_id else "", "convoy": False}
    if error:
        out["error"] = error
    return out


def _is_turvo_configured(tenant_slug: Optional[str]) -> bool:
    slug = (tenant_slug or "").strip()
    if not slug:
        return False
    from app.services.turvo_oauth_service import TurvoOAuthService

    return TurvoOAuthService().has_tms_partner_config(slug)


def _effective_tenant_slug(tenant_slug: Optional[str]) -> Optional[str]:
    return (tenant_slug or settings.TURVO_DEFAULT_TENANT_SLUG or "").strip() or None


def get_shipment(
    shipment_id: Any,
    *,
    tenant_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Return Turvo shipment details for a given shipment id.

    ``tenant_slug`` must be supplied by the caller when a live fetch is needed
    (nodes use ``state.data["tenant_slug"]``).

    Falls back to a minimal stub when Turvo is not configured or ``tenant_slug``
    is missing, so workflows remain testable without live Turvo creds.
    """
    if not shipment_id:
        return _stub_shipment(shipment_id)

    slug = _effective_tenant_slug(tenant_slug)
    if not slug or not _is_turvo_configured(slug):
        logger.info(
            "Turvo not configured or tenant_slug missing; returning stub shipment for %s",
            shipment_id,
        )
        return _stub_shipment(shipment_id)

    try:
        return asyncio.run(get_shipment_async(slug, shipment_id))
    except TurvoApiError as e:
        logger.warning(
            "Turvo get_shipment failed for shipment_id=%s status=%s body=%s",
            shipment_id,
            e.status_code,
            e.body,
        )
        stub = _stub_shipment(shipment_id, error=str(e))
        if is_tms_connection_timeout(e):
            stub["turvo_connection_timed_out"] = True
        return stub
    except ValueError as e:
        logger.warning("Invalid Turvo get_shipment call: %s", e)
        return _stub_shipment(shipment_id, error=str(e))
    except Exception:
        logger.exception("Unexpected error fetching Turvo shipment %s", shipment_id)
        return _stub_shipment(shipment_id, error="unexpected_error")


def check_pod_by_shipment_id(
    shipment_id: Any,
    *,
    tenant_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Return whether Turvo documents list includes proof of delivery for this shipment."""
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
    slug = _effective_tenant_slug(tenant_slug)
    if not slug or not _is_turvo_configured(slug):
        logger.info(
            "Turvo not configured or tenant_slug missing; skipping POD check for %s",
            sid,
        )
        return {
            "success": False,
            "shipment_id": sid,
            "pod_exists": False,
            "pod_documents": [],
            "all_documents_count": 0,
            "message": "Turvo not configured or tenant_slug missing",
        }

    try:
        return asyncio.run(check_pod_by_shipment_id_async(slug, shipment_id))
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


def load_id_to_shipment_id(
    load_id: Any,
    *,
    tenant_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve Turvo load/custom id to canonical ``shipment_id`` via search + shipment API."""
    empty = {
        "success": False,
        "load_id": "",
        "shipment_id": None,
        "message": "load_id is required",
    }
    if load_id is None or not str(load_id).strip():
        return empty

    lid = str(load_id).strip()
    slug = _effective_tenant_slug(tenant_slug)
    if not slug or not _is_turvo_configured(slug):
        logger.info(
            "Turvo not configured or tenant_slug missing; skipping load_id resolution for %s",
            lid,
        )
        return {
            "success": False,
            "load_id": lid,
            "shipment_id": None,
            "message": "Turvo not configured or tenant_slug missing",
        }

    try:
        sid = asyncio.run(load_id_to_shipment_id_async(slug, lid))
        if sid is None:
            return {
                "success": False,
                "load_id": lid,
                "shipment_id": None,
                "message": "No shipment found for load_id or could not extract shipment_id",
            }
        return {
            "success": True,
            "load_id": lid,
            "shipment_id": sid,
            "message": "ok",
        }
    except TurvoApiError as e:
        logger.warning(
            "Turvo load_id_to_shipment_id failed load_id=%s status=%s body=%s",
            lid,
            e.status_code,
            e.body,
        )
        return {
            "success": False,
            "load_id": lid,
            "shipment_id": None,
            "message": f"Failed to resolve load_id: {e}",
        }
    except ValueError as e:
        logger.warning("Invalid Turvo load_id_to_shipment_id call: %s", e)
        return {
            "success": False,
            "load_id": lid,
            "shipment_id": None,
            "message": str(e),
        }
    except Exception:
        logger.exception("Unexpected error resolving Turvo load_id %s", lid)
        return {
            "success": False,
            "load_id": lid,
            "shipment_id": None,
            "message": "Failed to resolve load_id: unexpected_error",
        }


def update_shipment(data: dict[str, Any]) -> None:
    """Placeholder for Turvo shipment update; replace with real endpoint when wired."""
    return data
    logger.info("[SHIPMENT UPDATE] shipment_id=%s (update not wired)", data.get("shipment_id"))


def upload_to_turvo(data: dict[str, Any]) -> dict[str, Any]:
    """Push merged POD PDF to TMS for the shipment in ``data``.

    Expects merged POD object key on ``data`` (see ``resolve_merged_pod_object_key``),
    plus ``shipment_id`` and ``tenant_slug``.
    """
    shipment_id = resolve_shipment_id(data)
    merged_key, _ = resolve_merged_pod_object_key(data)
    slug = _effective_tenant_slug(data.get("tenant_slug"))

    failed = {
        "success": False,
        "shipment_id": shipment_id or "",
        "message": "upload_to_turvo failed",
        "document": None,
    }
    if not shipment_id:
        return {**failed, "message": "missing_shipment_id"}
    if not merged_key:
        return {**failed, "message": "missing_pod_merged_pdf_object_key"}
    if not slug or not _is_turvo_configured(slug):
        return {**failed, "message": "Turvo not configured or tenant_slug missing"}

    download = bucket.download_object_bytes(str(merged_key))
    if not download.get("success") or not download.get("body"):
        return {
            **failed,
            "message": download.get("error_message") or "S3 download failed",
        }

    pdf_bytes = download["body"]
    filename = str(merged_key).rsplit("/", 1)[-1] or f"pod_{shipment_id}.pdf"

    try:
        upload_bytes, optimize_meta = optimize_for_tms_upload(
            pdf_bytes,
            max_bytes=settings.TURVO_POD_UPLOAD_MAX_BYTES,
            dpi=settings.TURVO_POD_OPTIMIZE_DPI,
            jpeg_quality=settings.TURVO_POD_OPTIMIZE_JPEG_QUALITY,
            max_side_px=settings.TURVO_POD_OPTIMIZE_MAX_SIDE_PX,
            shipment_id=shipment_id,
        )
        lookup_id = asyncio.run(resolve_pod_lookup_id(slug))
        max_attempts = max(1, settings.TURVO_POD_UPLOAD_MAX_ATTEMPTS)
        last_turvo_error: TurvoApiError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                shipment_payload = asyncio.run(get_shipment_async(slug, shipment_id))
                document_name = default_pod_document_name(shipment_id, shipment_payload)
                result = asyncio.run(
                    upload_pod_document(
                        slug,
                        shipment_id,
                        pdf_bytes=upload_bytes,
                        filename=filename,
                        document_name=document_name,
                        lookup_id=lookup_id,
                    )
                )
                if isinstance(result, dict) and not result.get("success"):
                    message = str(result.get("message") or "")
                    if attempt < max_attempts and "http error" in message.lower():
                        logger.warning(
                            "upload_to_turvo retry shipment_id=%s attempt=%s message=%s",
                            shipment_id,
                            attempt,
                            message[:200],
                        )
                        time.sleep(2 * attempt)
                        continue
                if isinstance(result, dict):
                    result["optimization"] = optimize_meta
                return result
            except TurvoApiError as err:
                last_turvo_error = err
                retryable = err.status_code is None or (
                    err.status_code is not None and err.status_code >= 500
                )
                if attempt < max_attempts and retryable:
                    logger.warning(
                        "upload_to_turvo retry shipment_id=%s attempt=%s status=%s error=%s",
                        shipment_id,
                        attempt,
                        err.status_code,
                        err,
                    )
                    time.sleep(2 * attempt)
                    continue
                raise
        if last_turvo_error is not None:
            raise last_turvo_error
        return {**failed, "message": "TMS upload failed after retries"}
    except PdfTooLargeError as e:
        logger.warning(
            "upload_to_turvo PDF too large to rasterize safely shipment_id=%s: %s",
            shipment_id,
            e,
        )
        return {
            **failed,
            "error": PdfTooLargeError.error_key,
            "message": PdfTooLargeError.error_key,
            "optimization": {"optimized": False, "error": str(e)},
        }
    except PodPdfOptimizeError as e:
        logger.warning(
            "upload_to_turvo optimize failed shipment_id=%s: %s",
            shipment_id,
            e,
        )
        return {
            **failed,
            "error": PdfTooLargeError.error_key,
            "message": "pdf_too_large_for_tms_after_optimization",
            "optimization": {"optimized": True, "error": str(e)},
        }
    except TurvoApiError as e:
        logger.warning(
            "upload_to_turvo failed shipment_id=%s status=%s",
            shipment_id,
            e.status_code,
        )
        return {**failed, "message": f"TMS upload failed: {e}"}
    except ValueError as e:
        logger.warning("upload_to_turvo invalid call shipment_id=%s: %s", shipment_id, e)
        return {**failed, "message": str(e)}
    except Exception:
        logger.exception("upload_to_turvo unexpected error shipment_id=%s", shipment_id)
        return {**failed, "message": "TMS upload failed: unexpected_error"}
