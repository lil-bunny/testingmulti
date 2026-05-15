from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException

from app.core.config import settings
from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.turvo_oauth_service import TurvoOAuthService
from app.services.workflow_service import WorkflowService


def get_workflow_service() -> WorkflowService:
    return WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )


def get_turvo_oauth_service() -> TurvoOAuthService:
    return TurvoOAuthService()


def require_turvo_public_api_config() -> None:
    if not (
        settings.TURVO_PUBLICAPI_URL
        and settings.TURVO_PUBLICAPI_CLIENT_ID
        and settings.TURVO_PUBLICAPI_CLIENT_SECRET
    ):
        raise HTTPException(
            status_code=503,
            detail="Turvo Public API is not configured. Set TURVO_PUBLICAPI_URL, "
            "TURVO_PUBLICAPI_CLIENT_ID, and TURVO_PUBLICAPI_CLIENT_SECRET.",
        )


def get_app_user_id(
    x_app_user_id: Annotated[Optional[str], Header(alias="X-App-User-Id")] = None,
) -> str:
    s = (x_app_user_id or "").strip()
    if s:
        return s
    fb = (settings.TURVO_DEFAULT_APP_USER_ID or "").strip()
    if fb:
        return fb
    raise HTTPException(
        status_code=400,
        detail="Header X-App-User-Id is required, or set TURVO_DEFAULT_APP_USER_ID.",
    )
