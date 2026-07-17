"""Resolve graph tenant keys to UUID for E2E queries."""

from __future__ import annotations


from app.repositories.tenants_db_repository import TenantsDbRepository
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def resolve_tenant_uuid(session: Session, tenant_id: str) -> str | None:
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    return TenantsDbRepository(session).resolve_graph_tenant_to_uuid(tid)
