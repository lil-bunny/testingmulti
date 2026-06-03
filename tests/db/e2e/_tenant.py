"""Resolve graph tenant keys to UUID for E2E queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.tenants_db_repository import TenantsDbRepository


def resolve_tenant_uuid(session: Session, tenant_id: str) -> str | None:
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    return TenantsDbRepository(session).resolve_graph_tenant_to_uuid(tid)
