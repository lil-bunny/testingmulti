"""Test-only tenant seeding (e.g. conftest ``t3ra`` row)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sqlalchemy import text

from app.core.db import jsonb_param

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_TABLE = "tenants"


def ensure_seed_tenant_by_slug(
    session: Session,
    *,
    tenant_id: str,
    name: str,
    slug: str,
    settings: dict[str, Any] | None = None,
) -> None:
    """Insert minimal tenant row when missing (``ON CONFLICT (slug) DO NOTHING``)."""
    tid = tenant_id.strip()
    s = slug.strip()
    if not tid or not s:
        return
    session.execute(
        text(
            f"""
            INSERT INTO {_TABLE} (id, name, slug, settings)
            VALUES (
                CAST(:id AS uuid),
                :name,
                :slug,
                CAST(:settings AS jsonb)
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {
            "id": tid,
            "name": name,
            "slug": s,
            "settings": jsonb_param(settings or {}),
        },
    )
