"""
Exercise the mail_thread_capture webhook logic locally (same steps as the route).

  uv run python scripts/test_mail_thread_capture_pipeline.py

Uses the sample Unipile payload below (load_id 30381 -> Turvo customId 30381 -> shipment id 1000315335 on sandbox).
Does not start the HTTP server or run the full LangGraph workflow unless you use the API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

# Sample webhook body (Unipile)
PAYLOAD_RAW = r"""
{"event":"mail_received","email_id":"w3M0L_3pW7us8vCCqCzz6w","account_id":"FqA0zzsTQJ-5naFro793wQ","webhook_name":"langraphmailtest","date":"2026-05-05T12:18:27.000Z","from_attendee":{"display_name":"Debdut Bhaduri","identifier":"debdutrcks@gmail.com","identifier_type":"EMAIL_ADDRESS"},"to_attendees":[{"display_name":"Debdut Bhaduri","identifier":"deb@freightx.ai","identifier_type":"EMAIL_ADDRESS"}],"cc_attendees":[],"bcc_attendees":[],"reply_to_attendees":[],"subject":"Rate confirmation for shipment: #30381","body":"<html><head>\r\n<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\"></head><body><div dir=\"ltr\"><br></div></body></html>","body_plain":"","message_id":"<CAKHYPydAL48YjBd=dMZpFEthbs_+8LN0iYHuWqp90e08ejnZJA@mail.gmail.com>","provider_id":"AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAAAABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABHvLAJAAA=","read_date":null,"is_complete":true,"has_attachments":true,"attachments":[{"id":"AAMkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQBGAAAAAABBmaor414BTr2urgO19M5UBwCW4yb7HMvuT5hmNZT5eF0pAAAAAAEMAACW4yb7HMvuT5hmNZT5eF0pAABHvLAJAAABEgAQAFkkfP553XpIvmF_2rnmgag=","name":"Carrier_rate_confirmation_-__30381.pdf","extension":"pdf","size":48124,"mime":"application/pdf"}],"folders":["Inbox"],"role":"inbox","origin":"external","thread_id":"AAQkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQAQAMDQltZQqi1JrTLP7avn8rE=","deprecated_id":"w4F_ECliWSK0TRYMPV8TvQ"}
"""


def main() -> None:
    from app.core.config import settings
    from app.tools.email import check_ratecon_mail_payload
    from app.tools.workflow_correlation import ratecon_shipment_in_workflow_correlation

    raw = json.loads(PAYLOAD_RAW)
    payload = {
        "event_type": "email_received",
        "webhook_name": raw.get("webhook_name"),
        **raw,
    }

    print("=== Mail thread capture - same checks as POST /api/webhook/unipile/mail_thread_capture ===\n")
    wn = payload.get("webhook_name")
    exp = settings.UNIPILE_MAIL_THREAD_CAPTURE_WEBHOOK_NAME
    print(f"webhook_name: {wn!r}\nexpected:     {exp!r}\nmatch:        {wn == exp}")
    if wn != exp:
        print("\nStop: webhook name would 400 in API.")
        return

    rc = check_ratecon_mail_payload(payload)
    print("\n(1) check_ratecon_mail_payload:\n", json.dumps(rc, indent=2))
    if not rc.get("is_ratecon_mail"):
        print("\nStop: not_ratecon_mail (route would return ignored).")
        return

    app_user = settings.TURVO_DEFAULT_APP_USER_ID
    print(f"\n(2) Using TURVO_DEFAULT_APP_USER_ID: {app_user!r}")

    corr = ratecon_shipment_in_workflow_correlation(rc["load_id"], app_user_id=app_user)
    print("\n(3) ratecon_shipment_in_workflow_correlation:\n", json.dumps(corr, indent=2, default=str))

    if corr.get("in_workflow_correlation"):
        print(
            "\n(4) Route outcome: pod_lifecycle workflow (existing correlation; same as "
            "`POST /webhook/unipile` for mail_received). shipment_id:",
            corr.get("shipment_id"),
        )
    else:
        print(
            "\n(4) Route outcome: would run ratecon workflow to create correlation. Resolved shipment_id:",
            corr.get("shipment_id"),
        )
        print(
            "    Full graph: POST /api/webhook/unipile/mail_thread_capture with Authorization header."
        )


if __name__ == "__main__":
    main()
