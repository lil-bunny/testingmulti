"""Per-tenant Turvo Public API OAuth: authenticate and status (no raw tokens in responses)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_tenant_slug,
    get_turvo_oauth_service,
    require_turvo_public_api_config,
)
from app.core.logger import get_logger
from app.integrations.turvo.oauth_http import TurvoOAuthHttpError
from app.services.turvo_oauth_service import TurvoOAuthService
from pydantic import BaseModel, Field

router = APIRouter(prefix="/user/turvo", tags=["user-turvo"])
logger = get_logger(__name__)


class TurvoAuthenticateBody(BaseModel):
    """Per-user Turvo credentials (historical field names: client_id = username, client_secret = password)."""

    client_id: str = Field(min_length=1, description="Turvo username (per user)")
    client_secret: str = Field(min_length=1, description="Turvo password (per user)")


class TurvoAuthenticateResponse(BaseModel):
    success: bool = True
    expires_in: Optional[int] = None
    token_type: Optional[str] = None


class TurvoStatusResponse(BaseModel):
    linked: bool


@router.post(
    "/authenticate",
    response_model=TurvoAuthenticateResponse,
    dependencies=[Depends(require_turvo_public_api_config)],
    summary="Link Turvo account (password grant) and store tokens server-side",
)
async def turvo_authenticate(
    body: TurvoAuthenticateBody,
    tenant_slug: str = Depends(get_tenant_slug),
    service: TurvoOAuthService = Depends(get_turvo_oauth_service),
) -> TurvoAuthenticateResponse:
    try:
        out = await service.authenticate_tenant(
            tenant_slug=tenant_slug,
            turvo_username=body.client_id,
            turvo_password=body.client_secret,
        )
    except TurvoOAuthHttpError as e:
        logger.warning("Turvo OAuth failed: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Turvo authentication failed",
        ) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("Unexpected error during Turvo OAuth")
        raise HTTPException(status_code=500, detail="Internal error") from e

    return TurvoAuthenticateResponse(
        success=bool(out.get("success", True)),
        expires_in=out.get("expires_in"),
        token_type=out.get("token_type"),
    )


@router.get(
    "/status",
    response_model=TurvoStatusResponse,
    summary="Whether this tenant has Turvo credentials stored (no secrets)",
)
async def turvo_status(
    tenant_slug: str = Depends(get_tenant_slug),
    service: TurvoOAuthService = Depends(get_turvo_oauth_service),
) -> TurvoStatusResponse:
    try:
        linked = service.has_oauth(tenant_slug)
    except Exception as e:
        logger.exception("Failed to read Turvo status")
        raise HTTPException(status_code=500, detail="Internal error") from e
    return TurvoStatusResponse(linked=linked)
