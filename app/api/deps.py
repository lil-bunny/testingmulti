from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException

from app.core.config import settings
from app.core.logger import get_logger
from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.turvo_oauth_service import TurvoOAuthService
from app.services.workflow_service import WorkflowService

logger = get_logger(__name__)


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

