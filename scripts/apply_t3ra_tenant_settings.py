"""Apply t3ra tenant settings JSON to tenants.settings (deep merge, preserve secrets).

Usage:
  uv run python scripts/apply_t3ra_tenant_settings.py --env dev
  uv run python scripts/apply_t3ra_tenant_settings.py --env staging
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg

from app.core.config import settings

_SETTINGS_DIR = _ROOT / "scripts/tenant_settings/t3ra"
_PRESERVE_TOP_LEVEL_KEYS = frozenset({"tms", "mikey_account_id", "inbound_routing_emails"})


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, val in overlay.items():
        if key in _PRESERVE_TOP_LEVEL_KEYS:
            continue
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def _merge_enabled_processes(current: list[str], fixture: list[str]) -> list[str]:
    merged: list[str] = []
    for name in list(current) + list(fixture):
        cleaned = str(name).strip()
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply t3ra tenant settings fixture to DB.")
    parser.add_argument(
        "--env",
        choices=("dev", "staging"),
        default="dev",
        help="Which fixture file to apply (default: dev).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixture_path = _SETTINGS_DIR / f"t3ra.tenant_settings.{args.env}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    if not settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not configured")

    conn = psycopg.connect(settings.DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT settings FROM tenants WHERE slug = 't3ra'")
            row = cur.fetchone()
            if not row:
                raise SystemExit("t3ra tenant not found")

            current = row[0] or {}
            if isinstance(current, str):
                current = json.loads(current)

            preserved = {k: current[k] for k in _PRESERVE_TOP_LEVEL_KEYS if k in current}
            merged = _deep_merge(current, fixture)
            merged.update(preserved)

            cur_enabled = merged.get("enabledProcesses")
            fix_enabled = fixture.get("enabledProcesses")
            if isinstance(cur_enabled, list) and isinstance(fix_enabled, list):
                merged["enabledProcesses"] = _merge_enabled_processes(cur_enabled, fix_enabled)

            cur.execute(
                "UPDATE tenants SET settings = %s::jsonb WHERE slug = 't3ra' RETURNING settings",
                (json.dumps(merged),),
            )
            updated = cur.fetchone()[0]

        print(f"Applied fixture: {fixture_path.name}")
        print(f"DATABASE: {settings.DATABASE_NAME}")
        print("enabledProcesses:", updated.get("enabledProcesses"))
        print(
            "has driver_assignment.confirmation_email:",
            "confirmation_email"
            in (updated.get("driver_assignment") or {}),
        )
        print("mikey_account_id preserved:", updated.get("mikey_account_id") == preserved.get("mikey_account_id"))
        print("tms.access_token preserved:", bool(preserved.get("tms")))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
