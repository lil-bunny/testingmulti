from collections.abc import Generator
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.errors import http_error
from app.core.config import settings
from app.core.db import get_db_session
from app.core.logger import get_logger
from app.core.request_context import (
    bind_auth_context_from_user,
    bind_request_state_from_context,
    resolve_tenant_slug,
)
from app.domain.api_user import ApiUser
from app.domain.auth_errors import (
    AuthServiceUnavailableError,
    AuthUnauthorizedError,
    ForbiddenError,
)
from app.integrations.freightx_api.auth_client import validate_token
from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.turvo_oauth_service import TurvoOAuthService
from app.services.workflow_service import WorkflowService

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


def get_session() -> Generator[Session, None, None]:
    yield from get_db_session()


def get_workflow_service() -> WorkflowService:
    return WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )


def get_turvo_oauth_service() -> TurvoOAuthService:
    return TurvoOAuthService()


def get_tenant_slug(
    x_tenant_slug: Annotated[Optional[str], Header(alias="X-Tenant-Slug")] = None,
    x_app_user_id: Annotated[Optional[str], Header(alias="X-App-User-Id")] = None,
) -> str:
    slug = (x_tenant_slug or "").strip()
    if slug:
        return slug
    legacy = (x_app_user_id or "").strip()
    if legacy:
        logger.warning(
            "X-App-User-Id is deprecated for Turvo OAuth; use X-Tenant-Slug (received %r)",
            legacy,
        )
        return legacy
    fb = (settings.TURVO_DEFAULT_TENANT_SLUG or "").strip()
    if fb:
        return fb
    raise HTTPException(
        status_code=400,
        detail="Header X-Tenant-Slug is required, or set TURVO_DEFAULT_TENANT_SLUG.",
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> ApiUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise http_error(
            401,
            "unauthorized",
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user = await validate_token(credentials.credentials)
    except AuthUnauthorizedError as exc:
        raise http_error(
            401,
            "unauthorized",
            str(exc) or "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthServiceUnavailableError as exc:
        raise http_error(
            503,
            "service_unavailable",
            str(exc) or "Authentication service unavailable",
        ) from exc

    slug: str | None = None
    if user.tenant_id:
        try:
            slug = resolve_tenant_slug(session, UUID(user.tenant_id))
        except ValueError:
            slug = None

    bind_auth_context_from_user(user=user, tenant_slug=slug)
    bind_request_state_from_context(request)
    return user


def get_tenant_slug_for_user(
    user: Annotated[ApiUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    x_tenant_slug: Annotated[Optional[str], Header(alias="X-Tenant-Slug")] = None,
) -> str:
    if not user.tenant_id:
        raise ForbiddenError("No active tenant on token")

    try:
        tenant_uuid = UUID(user.tenant_id)
    except ValueError as exc:
        raise ForbiddenError("Invalid tenant on token") from exc

    slug = resolve_tenant_slug(session, tenant_uuid)
    if not slug:
        raise ForbiddenError("Tenant not found for token")

    header_slug = (x_tenant_slug or "").strip()
    if header_slug and header_slug.lower() != slug.lower():
        raise ForbiddenError("X-Tenant-Slug does not match token tenant")

    return slug


def require_turvo_public_api_config(
    tenant_slug: Annotated[str, Depends(get_tenant_slug)],
) -> None:
    if not TurvoOAuthService().has_tms_partner_config(tenant_slug):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Tenant {tenant_slug!r} has no complete tenants.settings.tms block "
                "(public_api_url, client_id, client_secret, x_api_key required)."
            ),
        )


def require_turvo_public_api_config_for_slug(
    tenant_slug: Annotated[str, Depends(get_tenant_slug_for_user)],
) -> str:
    if not TurvoOAuthService().has_tms_partner_config(tenant_slug):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Tenant {tenant_slug!r} has no complete tenants.settings.tms block "
                "(public_api_url, client_id, client_secret, x_api_key required)."
            ),
        )
    return tenant_slug


def require_turvo_oauth_linked(
    tenant_slug: Annotated[str, Depends(get_tenant_slug)],
    service: Annotated[TurvoOAuthService, Depends(get_turvo_oauth_service)],
) -> str:
    """Ensure tenant has linked Turvo OAuth tokens before outbound TMS calls."""
    if not service.has_oauth(tenant_slug):
        raise HTTPException(
            status_code=401,
            detail=f"Turvo account not linked for tenant {tenant_slug!r}",
        )
    return tenant_slug


def require_turvo_oauth_linked_for_slug(
    tenant_slug: Annotated[str, Depends(require_turvo_public_api_config_for_slug)],
    service: Annotated[TurvoOAuthService, Depends(get_turvo_oauth_service)],
) -> str:
    """Auth-scoped Turvo OAuth check (tenant from token, not X-Tenant-Slug alone)."""
    if not service.has_oauth(tenant_slug):
        raise HTTPException(
            status_code=401,
            detail=f"Turvo account not linked for tenant {tenant_slug!r}",
        )
    return tenant_slug
