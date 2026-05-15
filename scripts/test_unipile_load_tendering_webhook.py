"""
POST /api/webhook/unipile with a sample Unipile payload shaped for load_tendering.

Prerequisites (local server must match):
  - UNIPILE_WEBHOOK_SECRET=123456  (same value as --token below)
  - GELLITA_UNIPILE_ID=W7Xyw8gLT2mvog37VsGHZQ  (must match payload account_id)
  - UNIPILE_WEBHOOK_NAME=pod_lifecycle_email_received_webhook  (must match payload webhook_name)

Run API:  uv run uvicorn app.main:app --reload --port 8000
Run script:  uv run python scripts/test_unipile_load_tendering_webhook.py
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_TOKEN = "123456"

SAMPLE_LOAD_TENDERING_PAYLOAD = {
    "event": "mail_received",
    "email_id": "lPFp14lSWJS0Geg_xmt_jA",
    "account_id": "W7Xyw8gLT2mvog37VsGHZQ",
    "webhook_name": "pod_lifecycle_email_received_webhook",
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
            "name": "Customer orders (1).xlsx",
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

    url = f"{args.base_url.rstrip('/')}/api/webhook/unipile"

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
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
