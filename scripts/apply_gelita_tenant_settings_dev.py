"""One-off: apply gelita.tenant_settings.dev.json to tenants.settings for slug gelita.

Usage:
  uv run python scripts/apply_gelita_tenant_settings_dev.py
  uv run python scripts/apply_gelita_tenant_settings_dev.py --vendor-email you+test@example.com

By default, vendor_email values come from the JSON fixture. Pass --vendor-email to
override LTL and FTL send_tender_email vendor_email (repeatable for multiple addresses).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg

from app.core.config import settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply gelita.tenant_settings.dev.json to tenants.settings for slug gelita."
    )
    parser.add_argument(
        "--vendor-email",
        action="append",
        default=None,
        metavar="EMAIL",
        help="Override LTL/FTL vendor_email (repeatable). Omit to keep fixture values.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixture = json.loads(
        (_ROOT / "scripts/tenant_settings/gelita/gelita.tenant_settings.dev.json").read_text(
            encoding="utf-8"
        )
    )
    if not settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not configured")

    vendor_overridden = bool(args.vendor_email)
    if vendor_overridden:
        fixture["load_tendering"]["ltl"]["send_tender_email"]["vendor_email"] = (
            args.vendor_email
        )
        fixture["load_tendering"]["ftl"]["send_tender_email"]["vendor_email"] = (
            args.vendor_email
        )

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

            for acct_key in ("ana_at_gelita_account_id",):
                if current.get(acct_key):
                    fixture[acct_key] = current[acct_key]

            cur.execute(
                "UPDATE tenants SET settings = %s::jsonb WHERE slug = %s RETURNING settings",
                (json.dumps(fixture), "gelita"),
            )
            updated = cur.fetchone()[0]

        print(f"DATABASE: {settings.DATABASE_NAME}")
        print(
            "vendor_email source:",
            "CLI override" if vendor_overridden else "fixture (no --vendor-email)",
        )
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
