"""v1 per-tenant Turvo Public API OAuth: authenticate and status (no raw tokens in responses)."""

from __future__ import annotations

from typing import Annotated, Optional, TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    get_tenant_slug,
    get_turvo_oauth_service,
    require_turvo_public_api_config,
)
from app.core.logger import get_logger
from app.integrations.turvo.oauth_http import TurvoOAuthHttpError

if TYPE_CHECKING:
    from app.services.turvo_oauth_service import TurvoOAuthService

router = APIRouter(prefix="/user/turvo", tags=["turvo"])
logger = get_logger(__name__)


class TurvoAuthenticateBody(BaseModel):
    client_id: str = Field(min_length=1, description="Turvo username")
    client_secret: str = Field(min_length=1, description="Turvo password")


class TurvoAuthenticateResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    expires_in: Optional[int] = Field(None, description="Token lifetime in seconds")
    token_type: Optional[str] = Field(None, description="Token type")


class TurvoStatusResponse(BaseModel):
    linked: bool = Field(..., description="Whether a Turvo account is linked")


@router.post(
    "/authenticate",
    response_model=TurvoAuthenticateResponse,
    dependencies=[Depends(require_turvo_public_api_config)],
    summary="Link Turvo account",
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Unauthorized"},
        503: {"description": "Service unavailable"},
    },
)
async def turvo_authenticate(
    body: Annotated[TurvoAuthenticateBody, Body()],
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
    summary="Turvo link status",
    responses={
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"},
    },
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
