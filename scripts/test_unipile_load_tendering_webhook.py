"""
POST /api/webhook/email with a sample Unipile payload shaped for Gelita load_tendering (xlsx).

Prerequisites (local server must match):
  - UNIPILE_WEBHOOK_SECRET — same as ``--token`` below
  - ``tenants.settings.email_webhook_name`` must match the base of the payload's
    ``webhook_name`` (this sample uses ``gelita_{ENV}``; ``ENV`` must match the API deployment).
    Route auth is Bearer-only; tenant/import routing is DB-driven from that base name.

Run API:  uv run uvicorn app.main:app --reload --port 8001
Run script:  uv run python scripts/test_unipile_load_tendering_webhook.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from app.core.config import settings

DEFAULT_BASE = "http://127.0.0.1:8001"
WEBHOOK_PATH = "/api/webhook/email"
DEFAULT_TOKEN = "123456"

SAMPLE_LOAD_TENDERING_PAYLOAD = {
    "event": "mail_received",
    "email_id": "lPFp14lSWJS0Geg_xmt_jA",
    "account_id": "W7Xyw8gLT2mvog37VsGHZQ",
    "webhook_name": f"gelita_{settings.ENV}",
    "date": "2026-05-14T11:31:25.000Z",
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
    "subject": "",
    "body": (
        '<html><head>\r\n<meta http-equiv="Content-Type" '
        'content="text/html; charset=utf-8"></head><body><div dir="ltr"><br>'
        "</div></body></html>"
    ),
    "body_plain": "",
    "message_id": "<CAKHYPyd+s1oRYiL6fsXkxgjVn9NnAND8h=b1XDNtLXtYFArCuw@mail.gmail.com>",
    "provider_id": (
        "AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAA"
        "AABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABNEJb9AAA="
    ),
    "read_date": None,
    "is_complete": True,
    "has_attachments": True,
    "attachments": [
        {
            "id": (
                "AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAA"
                "AABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABNEJb9AAAB"
                "EgAQANKM9dXEy3NDurxvEY6_aaE="
            ),
            "name": "customers_orders_sample.xlsx",
            "extension": "xlsx",
            "size": 15531,
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    ],
    "folders": ["Inbox"],
    "role": "inbox",
    "origin": "external",
    "thread_id": (
        "AAQkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQAQAL-b33Rb1gRFusq34gLOroA="
    ),
    "deprecated_id": "LT-PGuv2WwS5KCcbscaXcA",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="POST Unipile webhook sample for load_tendering.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE,
        help=f"API origin (default: {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help=f"Bearer token; must match UNIPILE_WEBHOOK_SECRET (default: {DEFAULT_TOKEN})",
    )
    parser.add_argument(
        "--payload-file",
        help="Optional JSON file to POST instead of the built-in sample",
    )
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}{WEBHOOK_PATH}"

    if args.payload_file:
        with open(args.payload_file, encoding="utf-8") as f:
            body: dict = json.load(f)
    else:
        body = SAMPLE_LOAD_TENDERING_PAYLOAD

    headers = {
        "Authorization": f"Bearer {args.token}",
        "Content-Type": "application/json",
    }

    print(f"POST {url}", file=sys.stderr)
    r = httpx.post(url, json=body, headers=headers, timeout=30.0)

    print(r.status_code, r.text)
    if r.status_code == 200:
        try:
            body = r.json()
            if body.get("message") == "accepted":
                print(
                    "Background ingest queued; check Celery worker logs for "
                    f"task_id={body.get('task_id')!r}",
                    file=sys.stderr,
                )
        except json.JSONDecodeError:
            pass
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
