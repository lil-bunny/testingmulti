"""
Call Turvo Public API GET /v1/shipments/list filtered by customId[eq].

Uses the sandbox host by forcing TURVO_PUBLICAPI_URL for this process so token
and API base stay consistent (set before importing app settings).

  uv run python scripts/test_turvo_shipments_list.py
  uv run python scripts/test_turvo_shipments_list.py --custom-id 30381
  uv run python scripts/test_turvo_shipments_list.py --app-user-id deb-test

Requires .env: linked Turvo OAuth for app_user_id, TURVO_X_API_KEY if your tenant uses it,
and sandbox client credentials matching the sandbox account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Sandbox base (docs: https://my-sandbox-publicapi.turvo.com/v1/shipments/list)
SANDBOX_PUBLICAPI_URL = "https://my-sandbox-publicapi.turvo.com"
os.environ["TURVO_PUBLICAPI_URL"] = SANDBOX_PUBLICAPI_URL

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Turvo GET /v1/shipments/list?customId[eq]=...")
    parser.add_argument(
        "--custom-id",
        default="30381",
        help="customId value for customId[eq] (default: 30381)",
    )
    parser.add_argument(
        "--app-user-id",
        default=os.getenv("TURVO_DEFAULT_APP_USER_ID", "") or "",
        help="Tenants.config OAuth row key (default: env TURVO_DEFAULT_APP_USER_ID)",
    )
    args = parser.parse_args()

    if not str(args.app_user_id).strip():
        print("ERROR: pass --app-user-id or set TURVO_DEFAULT_APP_USER_ID", file=sys.stderr)
        sys.exit(2)

    asyncio.run(_run(args.custom_id, str(args.app_user_id).strip()))


async def _run(custom_id: str, app_user_id: str) -> None:
    from app.core.config import settings
    from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError
    from app.integrations.turvo.public_api_urls import (
        build_publicapi_v1_url,
        normalize_turvo_publicapi_url,
    )

    base = normalize_turvo_publicapi_url(settings.TURVO_PUBLICAPI_URL or SANDBOX_PUBLICAPI_URL)
    url = build_publicapi_v1_url(base, "/shipments/list")
    params = {"customId[eq]": str(custom_id)}

    print("TURVO_PUBLICAPI_URL (effective):", settings.TURVO_PUBLICAPI_URL)
    print("Request URL:", url)
    print("Query:", params)
    print("app_user_id:", app_user_id)
    print()

    client = TurvoApiClient()
    try:
        data = await client.request(
            app_user_id,
            "GET",
            "/shipments/list",
            params=params,
        )
        print("Status: 200 OK (client raises on non-2xx)")
        print(json.dumps(data, indent=2, default=str))
    except TurvoApiError as e:
        print("TurvoApiError:", e, file=sys.stderr)
        if e.status_code is not None:
            print("HTTP status:", e.status_code, file=sys.stderr)
        if e.body:
            print("Body:", e.body[:2000], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
