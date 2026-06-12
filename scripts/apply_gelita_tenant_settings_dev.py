"""One-off: apply gelita.tenant_settings.dev.json to tenants.settings for slug gelita."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg

from app.core.config import settings

CARRIER_EMAIL = "debdutrucks@gmail.com"


def main() -> None:
    fixture = json.loads(
        (_ROOT / "scripts/tenant_settings/gelita/gelita.tenant_settings.dev.json").read_text(
            encoding="utf-8"
        )
    )
    if not settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not configured")

    conn = psycopg.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT settings FROM tenants WHERE slug = 'gelita'")
            row = cur.fetchone()
            if not row:
                raise SystemExit("gelita tenant not found")
            current = row[0] or {}
            if isinstance(current, str):
                current = json.loads(current)

            for acct_key in (
                "ana_at_gelita_account_id",
                "ana_gelita_at_freightx_ai_account_id",
            ):
                if current.get(acct_key):
                    fixture[acct_key] = current[acct_key]

            carrier = [CARRIER_EMAIL]
            fixture["load_tendering"]["ltl"]["send_tender_email"]["vendor_email"] = carrier
            fixture["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"] = carrier

            cur.execute(
                "UPDATE tenants SET settings = %s::jsonb WHERE slug = %s RETURNING settings",
                (json.dumps(fixture), "gelita"),
            )
            updated = cur.fetchone()[0]

        print(f"DATABASE: {settings.DATABASE_NAME}")
        print(
            "vendor_email LTL:",
            updated["load_tendering"]["ltl"]["send_tender_email"]["vendor_email"],
        )
        print(
            "vendor_email FTL:",
            updated["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"],
        )
        print("has prompts:", "prompts" in updated)
        print(
            "has email_subject LTL:",
            "email_subject" in updated["load_tendering"]["ltl"]["send_tender_email"],
        )
        print(
            "has pallet_profiles:",
            "pallet_profiles" in updated["load_tendering"]["tender_calculate"],
        )
        print(
            "workflow_error_alerts enabled:",
            updated["load_tendering"]["workflow_error_alerts"]["enabled"],
        )
        print("ana account:", updated.get("ana_at_gelita_account_id"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
