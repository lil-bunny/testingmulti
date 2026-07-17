"""
Manage a personal Unipile email webhook for local dev testing.

Idempotent by --name: `add` does nothing if a webhook with that name already
exists (use `update` to change its URL, `remove` to delete it first). This
avoids piling up duplicate/stale webhooks under different names every time
someone restarts ngrok.

If you use a reserved/static ngrok domain (the normal setup — a free-tier
random domain changes every restart, which defeats the point), set it once
in .env as NGROK_DOMAIN and skip passing --ngrok-domain on every call.

Usage:
  # find your connected account id first
  uv run python scripts/manage_unipile_webhook.py accounts

  # create (no-ops if freightx_dev_<you> already exists)
  # uses NGROK_DOMAIN from .env if --ngrok-domain is omitted
  uv run python scripts/manage_unipile_webhook.py add --account-id <unipile_account_id>

  # override the domain for one call without touching .env
  uv run python scripts/manage_unipile_webhook.py add \
      --ngrok-domain your-domain.ngrok-free.app \
      --account-id <unipile_account_id>

  uv run python scripts/manage_unipile_webhook.py update
  uv run python scripts/manage_unipile_webhook.py status
  uv run python scripts/manage_unipile_webhook.py remove

All commands default --name to `freightx_dev_<your OS username>` — pass
--name explicitly to manage a differently-named webhook.

Requires .env: UNIPILE_API_KEY, UNIPILE_DSN, UNIPILE_WEBHOOK_SECRET.
Optional .env: NGROK_DOMAIN (default --ngrok-domain for add/update).

Note: the webhook path is always /api/v1/webhook/email — this script builds
the full URL from --ngrok-domain/NGROK_DOMAIN so the path can't go stale
again. Use the raw --url flag only if you need a non-ngrok / non-standard
target.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

import httpx

from app.core.config import settings

WEBHOOK_PATH = "/api/v1/webhook/email"


def default_name() -> str:
    return f"freightx_dev_{getpass.getuser()}"


def check_env() -> list[str]:
    missing = [
        name
        for name in ("UNIPILE_API_KEY", "UNIPILE_DSN", "UNIPILE_WEBHOOK_SECRET")
        if not getattr(settings, name, None)
    ]
    return missing


def headers() -> dict[str, str]:
    return {"X-API-KEY": settings.UNIPILE_API_KEY, "Accept": "application/json"}


def list_webhooks(client: httpx.Client) -> list[dict]:
    resp = client.get(f"https://{settings.UNIPILE_DSN}/api/v1/webhooks", headers=headers())
    resp.raise_for_status()
    return resp.json().get("items", [])


def list_accounts(client: httpx.Client) -> list[dict]:
    resp = client.get(f"https://{settings.UNIPILE_DSN}/api/v1/accounts", headers=headers())
    resp.raise_for_status()
    return resp.json().get("items", [])


def find_by_name(webhooks: list[dict], name: str) -> dict | None:
    for w in webhooks:
        if w.get("name") == name:
            return w
    return None


def create_webhook(client: httpx.Client, *, name: str, url: str, account_id: str) -> dict:
    body = {
        "source": "email",
        "request_url": url,
        "name": name,
        "events": ["mail_received"],
        "enabled": True,
        "headers": [{"key": "Authorization", "value": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"}],
        "account_ids": [account_id],
    }
    resp = client.post(f"https://{settings.UNIPILE_DSN}/api/v1/webhooks", headers=headers(), json=body)
    resp.raise_for_status()
    return resp.json()


def delete_webhook(client: httpx.Client, webhook_id: str) -> None:
    resp = client.delete(f"https://{settings.UNIPILE_DSN}/api/v1/webhooks/{webhook_id}", headers=headers())
    resp.raise_for_status()


def resolve_url(args: argparse.Namespace) -> str:
    if args.url:
        return args.url
    domain = args.ngrok_domain or os.getenv("NGROK_DOMAIN")
    if domain:
        domain = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        return f"https://{domain}{WEBHOOK_PATH}"
    print(
        "Need a domain: pass --ngrok-domain, set NGROK_DOMAIN in .env (recommended if "
        "you use a reserved/static ngrok domain), or pass --url directly.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def cmd_accounts(_args: argparse.Namespace) -> int:
    with httpx.Client(timeout=15.0) as client:
        for a in list_accounts(client):
            print(f"{a.get('id')}\t{a.get('name')}\t{a.get('type')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with httpx.Client(timeout=15.0) as client:
        existing = find_by_name(list_webhooks(client), args.name)
    if not existing:
        print(f"No webhook named {args.name!r}.")
        return 0
    print(json.dumps(existing, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    if not args.account_id:
        print("--account-id is required for add (run `accounts` to find yours).", file=sys.stderr)
        return 1
    url = resolve_url(args)
    with httpx.Client(timeout=30.0) as client:
        existing = find_by_name(list_webhooks(client), args.name)
        if existing:
            print(f"Webhook {args.name!r} already exists (id={existing.get('id')}), doing nothing. Use `update` to change it.")
            return 0
        created = create_webhook(client, name=args.name, url=url, account_id=args.account_id)
        print(f"Created {args.name!r} -> {url}")
        print(json.dumps(created, indent=2) if created else "(created)")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    url = resolve_url(args)
    with httpx.Client(timeout=30.0) as client:
        existing = find_by_name(list_webhooks(client), args.name)
        if not existing:
            print(f"No webhook named {args.name!r} to update — use `add` instead.", file=sys.stderr)
            return 1
        account_id = args.account_id or (existing.get("account_ids") or [{}])[0].get("id")
        if not account_id:
            print("Could not determine account_id from the existing webhook; pass --account-id explicitly.", file=sys.stderr)
            return 1
        # Unipile's webhooks API has no PATCH/PUT — recreate under the same name.
        delete_webhook(client, existing["id"])
        created = create_webhook(client, name=args.name, url=url, account_id=account_id)
        print(f"Updated {args.name!r} -> {url}")
        print(json.dumps(created, indent=2) if created else "(updated)")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    with httpx.Client(timeout=15.0) as client:
        existing = find_by_name(list_webhooks(client), args.name)
        if not existing:
            print(f"No webhook named {args.name!r}, nothing to remove.")
            return 0
        delete_webhook(client, existing["id"])
        print(f"Removed {args.name!r} (id={existing['id']}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=None, help="Webhook name. Defaults to freightx_dev_<your OS username>.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_accounts = sub.add_parser("accounts", help="List connected Unipile accounts (to find --account-id).")
    p_accounts.set_defaults(func=cmd_accounts)

    p_status = sub.add_parser("status", help="Show the webhook's current config, if it exists.")
    p_status.set_defaults(func=cmd_status)

    p_add = sub.add_parser("add", help="Create the webhook. No-ops if it already exists.")
    p_add.add_argument("--ngrok-domain", default=None, help="e.g. your-domain.ngrok-free.app. Defaults to NGROK_DOMAIN in .env.")
    p_add.add_argument("--url", default=None, help="Full override URL instead of --ngrok-domain.")
    p_add.add_argument("--account-id", default=None, required=True, help="Unipile account id (see `accounts`).")
    p_add.set_defaults(func=cmd_add)

    p_update = sub.add_parser("update", help="Recreate the webhook with a new URL (Unipile has no PATCH).")
    p_update.add_argument("--ngrok-domain", default=None, help="e.g. your-new-domain.ngrok-free.app. Defaults to NGROK_DOMAIN in .env.")
    p_update.add_argument("--url", default=None, help="Full override URL instead of --ngrok-domain.")
    p_update.add_argument("--account-id", default=None, help="Only needed if changing the connected account too.")
    p_update.set_defaults(func=cmd_update)

    p_remove = sub.add_parser("remove", help="Delete the webhook.")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    if args.name is None:
        args.name = default_name()

    missing = check_env()
    if missing:
        print(f"Missing required .env value(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        return args.func(args)
    except httpx.HTTPStatusError as e:
        print(f"Unipile API error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
