"""
POST the Unipile mail_thread_capture webhook body and run the full ratecon graph
(same handler as ``app.api.routes.unipile_mail_thread_capture``).

In-process (default): uses FastAPI TestClient — no ``uvicorn`` required.
Against a running API: ``--base-url http://127.0.0.1:8000``

Requires ``.env`` (or env vars): ``UNIPILE_WEBHOOK_SECRET``, ``UNIPILE_MAIL_THREAD_CAPTURE_WEBHOOK_NAME``,
Turvo, DB, bucket, Unipile, etc., for a real end-to-end run.

  uv run python scripts/test_mail_thread_capture_webhook.py

  uv run python scripts/test_mail_thread_capture_webhook.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
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

PATH = "/api/webhook/unipile/mail_thread_capture"


def _post_in_process() -> tuple[int, dict[str, Any] | str]:
    from app.core.config import settings
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post(
        PATH,
        json=MAIL_RECEIVED_BODY,
        headers={"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"},
    )
    try:
        body: dict[str, Any] | str = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def _post_live(base_url: str) -> tuple[int, dict[str, Any] | str]:
    import httpx

    from app.core.config import settings

    url = base_url.rstrip("/") + PATH
    r = httpx.post(
        url,
        json=MAIL_RECEIVED_BODY,
        headers={"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"},
        timeout=120.0,
    )
    try:
        body: dict[str, Any] | str = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="POST mail_thread_capture sample payload (full ratecon workflow when not ignored)."
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="If set (e.g. http://127.0.0.1:8000), POST here instead of in-process app.",
    )
    args = parser.parse_args()

    if args.base_url:
        print(f"POST {args.base_url.rstrip('/')}{PATH} (live server)\n")
        status, body = _post_live(args.base_url)
    else:
        print(f"POST http://test{PATH} (TestClient / in-process)\n")
        status, body = _post_in_process()

    print(f"status: {status}")
    if isinstance(body, dict):
        print(json.dumps(body, indent=2, default=str))
    else:
        print(body)

    if status != 200:
        return 1

    if isinstance(body, dict) and body.get("message") == "ignored":
        print(
            "\n(note: workflow did not run — see reason above, e.g. "
            "not_ratecon_mail or already_in_workflow_correlation.)",
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
