"""Shared pytest hooks (unit + integration under ``tests/``)."""

from __future__ import annotations

import psycopg
import pytest

from app.core.config import settings


# Stable UUID for TENANT_CONFIGS key ``t3ra`` so FK-backed tables can join in local/CI DBs.
_GRAPH_T3RA_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"


@pytest.fixture(scope="session", autouse=True)
def _ensure_seed_tenant_t3ra() -> None:
    """Upsert a minimal ``tenants`` row for slug ``t3ra`` when Postgres is available.

    Workflow graph tests use ``tenant_id='t3ra'``; migrated schemas require ``workflow_lifecycles`` /
    ``workflow_runs`` to reference ``tenants.id`` (UUID). If the DB is unreachable or migrations are
    missing, ignore.
    """

    url = (settings.DATABASE_URL or "").strip()
    if not url:
        return
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenants (id, name, slug, settings)
                    VALUES (
                        %s::uuid,
                        'test tenant t3ra',
                        't3ra',
                        '{}'::jsonb
                    )
                    ON CONFLICT (slug) DO NOTHING
                    """,
                    (_GRAPH_T3RA_TENANT_UUID,),
                )
            conn.commit()
    except Exception:
        return
