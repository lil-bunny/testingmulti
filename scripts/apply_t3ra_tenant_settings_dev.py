"""One-off: apply t3ra.tenant_settings.dev.json to tenants.settings for slug t3ra.

Unlike Gelita, the identity_rbac migration doesn't seed a t3ra tenant row, so this
upserts one (INSERT if missing, UPDATE if present) rather than assuming it exists.

Deliberately NOT in the fixture JSON, since they're either secret or personal-per-developer:
  - tms (Turvo partner credentials) — pass via --tms-* flags, or omit and link later via
    POST /api/user/turvo/authenticate once your team has given you the partner client_id/
    client_secret/x_api_key (see README "Turvo setup").
  - mikey_account_id — your own Unipile-connected account id. Find it with:
    uv run python scripts/manage_unipile_webhook.py accounts
  - inbound_routing_emails — the email address(es) you connected to Unipile, that this
    tenant should treat as its inbox. Usually the same account as mikey_account_id.

Usage:
  uv run python scripts/apply_t3ra_tenant_settings_dev.py \
      --mikey-account-id <unipile_account_id> \
      --inbound-routing-email you@example.com

  # with Turvo partner creds (ask your team for these):
  uv run python scripts/apply_t3ra_tenant_settings_dev.py \
      --mikey-account-id <unipile_account_id> \
      --inbound-routing-email you@example.com \
      --tms-public-api-url https://my-sandbox-publicapi.turvo.com \
      --tms-ui-base-url https://my-sandbox.turvo.com \
      --tms-client-id publicapi \
      --tms-client-secret <from team> \
      --tms-x-api-key <from team>

  # dry run — print what would be written, don't touch the DB
  uv run python scripts/apply_t3ra_tenant_settings_dev.py --mikey-account-id x --inbound-routing-email y@z.com --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg

from app.core.config import settings

FIXTURE_PATH = _ROOT / "scripts/tenant_settings/t3ra/t3ra.tenant_settings.dev.json"
CONFIRMATION_EMAIL_PATH = (
    _ROOT / "scripts/tenant_settings/t3ra/driver_confirmation_email_templates.json"
)
TENANT_SLUG = "t3ra"
TENANT_NAME = "T3RA"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply t3ra.tenant_settings.dev.json to tenants.settings for slug t3ra."
    )
    parser.add_argument("--mikey-account-id", required=True, help="Your Unipile account id.")
    parser.add_argument(
        "--inbound-routing-email",
        action="append",
        required=True,
        metavar="EMAIL",
        help="Email address(es) this tenant should route inbound mail from (repeatable).",
    )
    parser.add_argument("--tms-public-api-url", default=None)
    parser.add_argument("--tms-ui-base-url", default=None)
    parser.add_argument("--tms-client-id", default=None)
    parser.add_argument("--tms-client-secret", default=None)
    parser.add_argument("--tms-x-api-key", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the settings that would be written without touching the DB.",
    )
    return parser.parse_args()


def build_tms_block(args: argparse.Namespace) -> dict | None:
    provided = {
        "public_api_url": args.tms_public_api_url,
        "ui_base_url": args.tms_ui_base_url,
        "client_id": args.tms_client_id,
        "client_secret": args.tms_client_secret,
        "x_api_key": args.tms_x_api_key,
    }
    if not any(provided.values()):
        return None
    missing = [k for k in ("public_api_url", "client_id", "client_secret", "x_api_key") if not provided.get(k)]
    if missing:
        raise SystemExit(
            f"Partial --tms-* flags given but missing: {', '.join(f'--tms-{m.replace(chr(95), chr(45))}' for m in missing)}. "
            "Provide all of public-api-url/client-id/client-secret/x-api-key, or none (link Turvo later)."
        )
    return {"provider": "turvo", **{k: v for k, v in provided.items() if v}}


def main() -> None:
    args = parse_args()
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    confirmation_email = json.loads(CONFIRMATION_EMAIL_PATH.read_text(encoding="utf-8"))
    fixture["driver_assignment"]["confirmation_email"] = confirmation_email

    fixture["mikey_account_id"] = {"account_id": args.mikey_account_id}
    fixture["inbound_routing_emails"] = args.inbound_routing_email

    tms = build_tms_block(args)
    if tms:
        fixture["tms"] = tms

    if args.dry_run:
        print(json.dumps(fixture, indent=2))
        print(
            "\n(dry run — nothing written. tms "
            + ("included" if tms else "omitted, link via /api/user/turvo/authenticate later")
            + ")"
        )
        return

    if not settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not configured")

    conn = psycopg.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tenants (id, name, slug, settings)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (slug) DO UPDATE SET settings = EXCLUDED.settings
                RETURNING id, settings
                """,
                (str(uuid.uuid4()), TENANT_NAME, TENANT_SLUG, json.dumps(fixture)),
            )
            tenant_id, updated = cur.fetchone()

        print(f"DATABASE: {settings.DATABASE_NAME}")
        print(f"tenant id: {tenant_id}")
        print("mikey_account_id:", updated.get("mikey_account_id"))
        print("inbound_routing_emails:", updated.get("inbound_routing_emails"))
        print("enabledProcesses:", updated.get("enabledProcesses"))
        print("has tms:", "tms" in updated)
        if "tms" not in updated:
            print(
                "No --tms-* flags given — link Turvo with your own sandbox login via "
                "POST /api/user/turvo/authenticate once the partner credentials are set."
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
