"""One-off: merge scripts/t3ra_tenant_settings.json into tenants.settings for slug t3ra."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg

from app.core.config import settings

fixture = json.loads(
    _ROOT.joinpath("scripts/t3ra_tenant_settings.json").read_text(encoding="utf-8")
)
if not settings.DATABASE_URL:
    raise SystemExit("DATABASE_URL is not configured")
conn = psycopg.connect(settings.DATABASE_URL)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT settings FROM tenants WHERE slug = 't3ra'")
    row = cur.fetchone()
    if not row:
        raise SystemExit("t3ra tenant not found")
    current = row[0] or {}
    if isinstance(current, str):
        current = json.loads(current)
    merged = {**current, **fixture}
    cur.execute(
        "UPDATE tenants SET settings = %s::jsonb WHERE slug = 't3ra' RETURNING settings",
        (json.dumps(merged),),
    )
    updated = cur.fetchone()[0]
    print(json.dumps(updated, indent=2))
conn.close()
