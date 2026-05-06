"""
POST the Unipile ``mail_thread_capture`` webhook — same handler as
``app.api.routes.unipile_mail_thread_capture`` (``POST /api/webhook/unipile``).

Default body is a sample ``mail_received`` ratecon email (subject #30381, attachment id
from Unipile). Override with ``--payload-file path.json``.

In-process (default): FastAPI TestClient — no ``uvicorn`` required.
Against a running API: ``--base-url http://127.0.0.1:8000`` (stub injection is skipped).

**Smoke stubs (default, in-process only):**
The app's sync Turvo tools use ``asyncio.run`` inside handlers, which fails under FastAPI /
TestClient (running event loop). Default S3 region/endpoint combos also often emit
``PermanentRedirect``. Without changing repo code, this script patches before ``app`` import:

- ``load_id_to_shipment_id`` → stable fake (avoids asyncio)
- ``S3Bucket`` global ``bucket.upload_file`` → success + fake ``object_key``

Use ``--integration`` on in-process runs to disable those stubs (real Turvo + S3; may error).

Requires ``.env`` for ``UNIPILE_WEBHOOK_SECRET``, webhook name alignment, DB, etc.

  uv run python scripts/test_mail_thread_capture_webhook.py

  uv run python scripts/test_mail_thread_capture_webhook.py --base-url http://127.0.0.1:8000

  uv run python scripts/test_mail_thread_capture_webhook.py --payload-file ./my_mail.json --integration
"""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

# Raw Unipile body (what the route receives before it adds event_type).
MAIL_RECEIVED_BODY: dict[str, Any] = {
    "event": "mail_received",
    "email_id": "w3M0L_3pW7us8vCCqCzz6w",
    "account_id": "FqA0zzsTQJ-5naFro793wQ",
    "webhook_name": "langraphmailtest",
    "date": "2026-05-05T12:18:27.000Z",
    "from_attendee": {
        "display_name": "Debdut Bhaduri",
        "identifier": "debdutrcks@gmail.com",
        "identifier_type": "EMAIL_ADDRESS",
    },
    "to_attendees": [
        {
            "display_name": "Debdut Bhaduri",
            "identifier": "deb@freightx.ai",
            "identifier_type": "EMAIL_ADDRESS",
        }
    ],
    "cc_attendees": [],
    "bcc_attendees": [],
    "reply_to_attendees": [],
    "subject": "Rate confirmation for shipment: #30381",
    "body": (
        '<html><head>\r\n<meta http-equiv="Content-Type" content="text/html; '
        'charset=utf-8"></head><body><div dir="ltr"><br></div></body></html>'
    ),
    "body_plain": "",
    "message_id": (
        "<CAKHYPydAL48YjBd=dMZpFEthbs_+8LN0iYHuWqp90e08ejnZJA@mail.gmail.com>"
    ),
    "provider_id": (
        "AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAAAABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABHvLAJAAA="
    ),
    "read_date": None,
    "is_complete": True,
    "has_attachments": True,
    "attachments": [
        {
            "id": (
                "AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAAAABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABHvLAJAAABEgAQAFkkfP553XpIvmF_2rnmgag="
            ),
            "name": "Carrier_rate_confirmation_-__30381.pdf",
            "extension": "pdf",
            "size": 48124,
            "mime": "application/pdf",
        }
    ],
    "folders": ["Inbox"],
    "role": "inbox",
    "origin": "external",
    "thread_id": (
        "AAQkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQAQAMDQltZQqi1JrTLP7avn8rE="
    ),
    "deprecated_id": "w4F_ECliWSK0TRYMPV8TvQ",
}

PATH = "/api/webhook/unipile"

_STUBS_ATTACHED = False


def _apply_in_process_smoke_stubs(*, shipment_id_hint: str | None) -> None:
    """Patch Turvo + S3 on modules already importing those symbols."""
    global _STUBS_ATTACHED
    if _STUBS_ATTACHED:
        return

    def smoke_load_id_to_shipment_id(
        load_id: Any,
        app_user_id: str | None = None,
    ) -> dict[str, Any]:
        empty = {
            "success": False,
            "load_id": "",
            "shipment_id": None,
            "message": "load_id is required",
        }
        if load_id is None or not str(load_id).strip():
            return empty
        lid = str(load_id).strip()
        if (shipment_id_hint or "").strip():
            sid = str(shipment_id_hint).strip()
        elif lid == "30381":
            # Matches sample payload / Turvo sandbox mapping from typical dev runs.
            sid = "1000315335"
        else:
            sid = f"SHIP-SMOKE-{lid}"
        return {
            "success": True,
            "load_id": lid,
            "shipment_id": sid,
            "message": "ok (test_mail_thread_capture_webhook stubs)",
        }

    def smoke_upload_file(
        self: Any,
        file_content: bytes,
        filename: str,
        content_type: str,
        folder: str = "pod_attachments",
    ) -> dict[str, Any]:
        return {
            "success": True,
            "object_key": f"freightx/{folder}/{filename}",
            "error_message": None,
        }

    import app.tools.turvo as turvo_mod
    import app.tools.workflow_correlation as wc_mod
    import app.workflows.nodes.turvo as turvo_nodes_mod
    from app.services import s3bucket_service as s3_mod

    for mod in (turvo_mod, wc_mod):
        mod.load_id_to_shipment_id = smoke_load_id_to_shipment_id
    turvo_nodes_mod.load_id_to_shipment_id_tool = smoke_load_id_to_shipment_id

    s3_mod.bucket.upload_file = types.MethodType(smoke_upload_file, s3_mod.bucket)

    _STUBS_ATTACHED = True
    print(
        "[test_mail_thread_capture_webhook] in-process stubs: Turvo load_id_to_shipment_id, "
        "bucket.upload_file (use --integration to disable).\n",
        flush=True,
    )


def _payload_from_args(payload_file: Path | None) -> dict[str, Any]:
    if payload_file is None:
        return dict(MAIL_RECEIVED_BODY)
    p = payload_file.expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"payload file not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("payload JSON must be an object")
    return raw


def _post_in_process(
    body: dict[str, Any], *, integration: bool, shipment_id_hint: str | None
) -> tuple[int, dict[str, Any] | str]:
    if not integration:
        _apply_in_process_smoke_stubs(shipment_id_hint=shipment_id_hint)

    from app.core.config import settings
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post(
        PATH,
        json=body,
        headers={"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"},
    )
    try:
        rb: dict[str, Any] | str = r.json()
    except Exception:
        rb = r.text
    return r.status_code, rb


def _post_live(base_url: str, body: dict[str, Any]) -> tuple[int, dict[str, Any] | str]:
    import httpx

    from app.core.config import settings

    url = base_url.rstrip("/") + PATH
    r = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"},
        timeout=120.0,
    )
    try:
        rb: dict[str, Any] | str = r.json()
    except Exception:
        rb = r.text
    return r.status_code, rb


def main() -> int:
    parser = argparse.ArgumentParser(
        description="POST mail_thread_capture sample payload (full ratecon workflow when not ignored)."
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="If set (e.g. http://127.0.0.1:8000), POST here instead of in-process app.",
    )
    parser.add_argument(
        "--payload-file",
        type=Path,
        default=None,
        help="Optional JSON file (Unipile mail body). Default: built-in sample ratecon payload.",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="In-process only: do not stub Turvo load resolution or S3 upload (live behavior).",
    )
    parser.add_argument(
        "--stub-shipment-id",
        default="",
        help="When stubs are on, pretend load_id resolves to this shipment id (default: SHIP-SMOKE-<load_id>).",
    )
    args = parser.parse_args()

    post_body = _payload_from_args(args.payload_file)
    hint = (args.stub_shipment_id or "").strip() or None

    if args.base_url:
        print(f"POST {args.base_url.rstrip('/')}{PATH} (live server; no stub injection)\n")
        status, body = _post_live(args.base_url, post_body)
    else:
        print(f"POST http://test{PATH} (TestClient / in-process)\n")
        status, body = _post_in_process(
            post_body,
            integration=bool(args.integration),
            shipment_id_hint=hint,
        )

    print(f"status: {status}")
    if isinstance(body, dict):
        print(json.dumps(body, indent=2, default=str))
    else:
        print(body)

    if status != 200:
        return 1

    if isinstance(body, dict) and body.get("message") == "ignored":
        print(
            "\n(note: workflow did not run — see reason above.)",
            file=sys.stderr,
        )
        return 0

    if isinstance(body, dict) and "data" in body:
        data = body["data"]
        print("\n--- ratecon workflow highlights ---")
        for key in (
            "shipment_id",
            "load_id_to_shipment",
            "ratecon_workflow_correlation",
            "ratecon_correlation_thread_persist",
            "ratecon_s3_upload",
        ):
            if key in data:
                print(f"{key}:", json.dumps(data[key], indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
