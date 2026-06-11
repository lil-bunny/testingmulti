"""Request-scoped context (contextvars) for tenant/user identity and logging."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.tenants_db_repository import TenantsDbRepository

if TYPE_CHECKING:
    from app.domain.api_user import ApiUser

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_tenant_slug: ContextVar[str | None] = ContextVar("tenant_slug", default=None)


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None
    user_id: str | None
    tenant_id: str | None
    tenant_slug: str | None


def clear_request_context() -> None:
    _request_id.set(None)
    _user_id.set(None)
    _tenant_id.set(None)
    _tenant_slug.set(None)


def bind_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def bind_auth_context_from_user(
    *,
    user: ApiUser,
    tenant_slug: str | None = None,
) -> RequestContext:
    user_id = str(user.id)
    tenant_id = str(user.tenant_id) if user.tenant_id else None
    _user_id.set(user_id)
    _tenant_id.set(tenant_id)
    _tenant_slug.set(tenant_slug)
    return get_request_context()


def get_request_context() -> RequestContext:
    return RequestContext(
        request_id=_request_id.get(),
        user_id=_user_id.get(),
        tenant_id=_tenant_id.get(),
        tenant_slug=_tenant_slug.get(),
    )


def get_active_tenant_id() -> str | None:
    """Active tenant UUID string from JWT-bound context (None if unset)."""
    return _tenant_id.get()


def bind_request_state_from_context(request: object) -> None:
    """Mirror context onto ``request.state`` for handlers and middleware."""
    ctx = get_request_context()
    state = request.state  # type: ignore[attr-defined]
    state.request_id = ctx.request_id
    state.user_id = ctx.user_id
    state.tenant_id = ctx.tenant_id
    state.tenant_slug = ctx.tenant_slug


def resolve_tenant_slug(session: Session, tenant_id: UUID | None) -> str | None:
    if tenant_id is None:
        return None
    return TenantsDbRepository(session).get_slug_for_tenant_uuid(str(tenant_id))
