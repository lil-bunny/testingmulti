"""
Live Turvo POD document upload smoke test (standalone script — no app code changes).

Mirrors the Postman call:
  POST /v1/documents?fullResponse=true&context=...&attributes=...
  multipart field ``attachment0``

Uses tenant OAuth tokens + ``tenants.settings.tms`` partner fields (same as ``TurvoApiClient``).

Run from repo root::

    uv run python scripts/test_turvo_pod_upload.py --shipment-id 1000324895

Optional::

    uv run python scripts/test_turvo_pod_upload.py --shipment-id 1000324895 --dry-run
    uv run python scripts/test_turvo_pod_upload.py --lookup-id 20271627 --pdf path/to/pod.pdf
    uv run python scripts/test_turvo_pod_upload.py --force   # upload even when POD exists
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.integrations.turvo.documents import check_pod_by_shipment_id
from app.integrations.turvo.public_api_urls import (
    build_publicapi_v1_url,
    normalize_turvo_publicapi_url,
)
from app.integrations.turvo.shipments import get_shipment
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.turvo_oauth_service import TurvoOAuthService

DEFAULT_SHIPMENT_ID = "1000324895"
# Turvo tenant document-type lookupId for "Proof of delivery" (sandbox t3ra).
# documentType.key ("3010") is NOT the upload lookupId — using it returns HTTP 500.
DEFAULT_POD_LOOKUP_ID = "20271627"

# Minimal valid PDF (one blank page) for upload when --pdf is omitted.
_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
trailer<</Size 4/Root 1 0 R>>
startxref
149
%%EOF
"""


def _tenant_slug(explicit: str | None) -> str:
    slug = (explicit or settings.TURVO_DEFAULT_TENANT_SLUG or "").strip()
    if not slug:
        raise SystemExit(
            "No tenant slug: pass --tenant-slug or set TURVO_DEFAULT_TENANT_SLUG in .env"
        )
    return slug


def _context_id_for_api(shipment_id: str) -> int | str:
    s = shipment_id.strip()
    if s.isdigit():
        return int(s)
    return s


def _shipment_display_number(shipment_payload: dict[str, Any]) -> str:
    details = shipment_payload.get("details")
    if isinstance(details, dict):
        for key in ("customId", "custom_id", "id"):
            raw = details.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    return ""


def _lookup_id_from_pod_docs(pod_documents: list[dict[str, Any]]) -> str | None:
    for doc in pod_documents:
        if not isinstance(doc, dict):
            continue
        for key in ("lookupId", "lookup_id"):
            raw = doc.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    return None


def _planned_skip_transition(
    *,
    shipment_id: str,
    pod_check: dict[str, Any],
) -> dict[str, Any]:
    """When POD already exists — no upload; optional idempotent activity note."""
    meta: dict[str, Any] = {
        "shipment_id": shipment_id,
        "pod_exists": True,
        "pod_documents_count": len(pod_check.get("pod_documents") or []),
        "skip_reason": "pod_already_present",
    }
    return {
        "upload_skipped": True,
        "reason": "POD already on Turvo shipment",
        "steps": [
            {
                "activity_type": ActivityType.ACTION.value,
                "description": "POD already present on Turvo; upload skipped",
                "metadata": meta,
            },
        ],
        "lifecycle_status": "unchanged",
    }


def _planned_activity_log_transition(
    *,
    shipment_id: str,
    upload_success: bool,
    turvo_response: dict[str, Any] | None,
) -> dict[str, Any]:
    """What a future ``record_pod_upload_activity`` node would emit (ratecon-style)."""
    meta: dict[str, Any] = {"shipment_id": shipment_id}
    if turvo_response:
        meta["turvo_upload_response"] = turvo_response

    if upload_success:
        return {
            "steps": [
                {
                    "activity_type": ActivityType.ACTION.value,
                    "description": "POD document uploaded to Turvo",
                    "metadata": meta,
                },
                {
                    "activity_type": ActivityType.SUB_STATUS_CHANGE.value,
                    "from_sub_status": StatusSubType.POD_STARTED.value,
                    "to_sub_status": StatusSubType.DOCUMENT_UPLOADED.value,
                    "metadata": meta,
                },
            ],
            "lifecycle_status": StatusType.PROCESSING.value,
        }

    return {
        "steps": [
            {
                "activity_type": ActivityType.ACTION.value,
                "description": "POD document upload to Turvo failed",
                "metadata": meta,
            },
            {
                "activity_type": ActivityType.STATUS_CHANGE.value,
                "from_status": StatusType.PROCESSING.value,
                "to_status": StatusType.FAILED.value,
                "metadata": meta,
            },
        ],
        "lifecycle_status": StatusType.FAILED.value,
    }


async def _resolve_auth(tenant_slug: str) -> tuple[str, str, str]:
    oauth = TurvoOAuthService()
    tms = await asyncio.to_thread(oauth._load_tms, tenant_slug)
    tokens = await oauth.get_tenant_tokens(tenant_slug)
    if not tokens or not tokens.get("access_token"):
        raise SystemExit(
            f"No Turvo access token for tenant {tenant_slug!r}. "
            "Link Turvo via /api/user/turvo/authenticate first."
        )
    public_api_url = (tms.public_api_url or "").strip()
    if not public_api_url:
        raise SystemExit(f"Tenant {tenant_slug!r} missing tms.public_api_url")
    x_key = (tms.x_api_key or "").strip()
    if not x_key:
        raise SystemExit(f"Tenant {tenant_slug!r} missing tms.x_api_key")
    base = normalize_turvo_publicapi_url(public_api_url)
    return tokens["access_token"], x_key, base


async def upload_pod_document(
    *,
    tenant_slug: str,
    shipment_id: str,
    pdf_path: Path,
    lookup_id: str,
    document_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    access_token, x_key, base = await _resolve_auth(tenant_slug)
    url = build_publicapi_v1_url(base, "/documents")

    context = {
        "id": _context_id_for_api(shipment_id),
        "type": "SHIPMENT",
    }
    attributes = {
        "name": document_name,
        "lookupId": lookup_id,
        "sharing": {"entities": []},
    }
    params = {
        "fullResponse": "true",
        "context": json.dumps(context, separators=(",", ":")),
        "attributes": json.dumps(attributes, separators=(",", ":")),
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "x-api-key": x_key,
    }

    request_preview = {
        "method": "POST",
        "url": url,
        "params": params,
        "headers": {k: ("Bearer ***" if k == "Authorization" else v) for k, v in headers.items()},
        "attachment": str(pdf_path),
    }
    print("\n=== Turvo POD upload request ===\n")
    print(json.dumps(request_preview, indent=2))

    if dry_run:
        return {"dry_run": True, "request": request_preview}

    pdf_bytes = pdf_path.read_bytes()
    files = {"attachment0": (pdf_path.name, pdf_bytes, "application/pdf")}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, params=params, headers=headers, files=files)

    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    result = {
        "status_code": resp.status_code,
        "body": body,
        "success": 200 <= resp.status_code < 300,
    }
    print("\n=== Turvo POD upload response ===\n")
    print(json.dumps(result, indent=2, default=str))
    return result


async def main_async(args: argparse.Namespace) -> int:
    tenant_slug = _tenant_slug(args.tenant_slug)
    shipment_id = str(args.shipment_id).strip()

    print(f"Tenant: {tenant_slug}")
    print(f"Shipment: {shipment_id}")

    print("\n=== POD check (before upload) ===\n")
    pod_before = await check_pod_by_shipment_id(tenant_slug, shipment_id)
    print(json.dumps(pod_before, indent=2, default=str))

    if pod_before.get("pod_exists") and not args.force:
        print("\n=== Upload skipped - POD already present ===\n")
        skip_transition = _planned_skip_transition(
            shipment_id=shipment_id,
            pod_check=pod_before,
        )
        print(json.dumps(skip_transition, indent=2, default=str))
        print(
            f"\nOK: {pod_before.get('message', 'POD found')}. "
            "Pass --force to upload anyway."
        )
        return 0

    if pod_before.get("pod_exists") and args.force:
        print("\nNote: POD already present but --force set; uploading anyway.\n")

    shipment_payload = await get_shipment(tenant_slug, shipment_id)
    display_no = _shipment_display_number(shipment_payload)
    default_name = f"Proof of delivery - #{display_no}" if display_no else f"Proof of delivery - {shipment_id}"
    document_name = (args.document_name or default_name).strip()

    lookup_id = (args.lookup_id or "").strip()
    if not lookup_id:
        lookup_id = _lookup_id_from_pod_docs(pod_before.get("pod_documents") or []) or ""
    if not lookup_id:
        lookup_id = (getattr(settings, "TURVO_POD_LOOKUP_ID", None) or "").strip()
    if not lookup_id:
        lookup_id = DEFAULT_POD_LOOKUP_ID
        print(
            f"\nNote: using default lookupId={lookup_id!r} for Proof of delivery. "
            "Override with --lookup-id or env TURVO_POD_LOOKUP_ID if needed."
        )

    if args.pdf:
        pdf_path = Path(args.pdf).expanduser().resolve()
        if not pdf_path.is_file():
            raise SystemExit(f"PDF not found: {pdf_path}")
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(_MINIMAL_PDF)
        tmp.flush()
        tmp.close()
        pdf_path = Path(tmp.name)
        print(f"\nUsing generated minimal test PDF: {pdf_path}")

    try:
        upload_result = await upload_pod_document(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
            pdf_path=pdf_path,
            lookup_id=lookup_id,
            document_name=document_name,
            dry_run=args.dry_run,
        )
    finally:
        if not args.pdf:
            pdf_path.unlink(missing_ok=True)

    upload_success = bool(upload_result.get("success"))
    turvo_body = upload_result.get("body")
    turvo_response = turvo_body if isinstance(turvo_body, dict) else None

    transition = _planned_activity_log_transition(
        shipment_id=shipment_id,
        upload_success=upload_success and not args.dry_run,
        turvo_response=turvo_response,
    )
    print("\n=== Planned activity log transition (future node) ===\n")
    print(json.dumps(transition, indent=2, default=str))

    if args.dry_run:
        print("\nDry run — upload skipped.")
        return 0

    print("\n=== POD check (after upload) ===\n")
    pod_after = await check_pod_by_shipment_id(tenant_slug, shipment_id)
    print(json.dumps(pod_after, indent=2, default=str))

    if not upload_success:
        return 1
    if pod_after.get("pod_exists"):
        print("\nOK: POD detected on shipment after upload.")
        return 0
    print("\nUpload returned success but POD not yet visible in documents/list (may lag).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Turvo POD document upload")
    parser.add_argument(
        "--shipment-id",
        default=DEFAULT_SHIPMENT_ID,
        help=f"Turvo shipment id (default: {DEFAULT_SHIPMENT_ID})",
    )
    parser.add_argument(
        "--tenant-slug",
        default=None,
        help="Tenant slug (default: TURVO_DEFAULT_TENANT_SLUG from .env)",
    )
    parser.add_argument(
        "--lookup-id",
        default=None,
        help="Turvo document type lookupId (auto from existing POD docs when possible)",
    )
    parser.add_argument(
        "--document-name",
        default=None,
        help='Document name attribute (default: "Proof of delivery - #<customId>")',
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="Path to PDF to upload (default: generated minimal PDF)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upload even when a POD document already exists on the shipment",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print request + planned activity transition without calling Turvo upload",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
