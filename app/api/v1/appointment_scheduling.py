"""Appointment scheduling HTTP routes (draft send enqueue)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Security, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, get_tenant_slug_for_user
from app.api.security import portal_bearer
from app.domain.api_user import ApiUser
from app.services.appointment_scheduling.send_service import (
    SendConflictError,
    SendService,
)

router = APIRouter(prefix="/appointment-scheduling", tags=["appointment-scheduling"])


class SendAppointmentDraftRequest(BaseModel):
    shipment_id: str | None = Field(
        default=None,
        description="Optional shipments.id for trace metadata",
    )


class SendAppointmentDraftResponse(BaseModel):
    execution_id: str = Field(..., description="Workflow run execution id")
    workflow_lifecycle_id: str = Field(..., description="Workflow lifecycle identifier")


@router.post(
    "/lifecycles/{workflow_lifecycle_id}/send",
    response_model=SendAppointmentDraftResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue appointment draft send",
    dependencies=[Security(portal_bearer)],
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        409: {"description": "Conflict"},
        422: {"description": "Unprocessable entity"},
    },
)
async def send_appointment_draft(
    workflow_lifecycle_id: Annotated[str, Path(description="Workflow lifecycle UUID")],
    body: SendAppointmentDraftRequest,
    user: Annotated[ApiUser, Depends(get_current_user)],
    tenant_slug: Annotated[str, Depends(get_tenant_slug_for_user)],
) -> SendAppointmentDraftResponse:
    service = SendService()
    try:
        execution_id = service.validate_and_enqueue_draft_send(
            tenant_slug=tenant_slug,
            workflow_lifecycle_id=workflow_lifecycle_id.strip(),
            actor_user_id=user.id,
            shipment_id=body.shipment_id,
        )
    except SendConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if detail == "lifecycle_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        ) from exc

    return SendAppointmentDraftResponse(
        execution_id=execution_id,
        workflow_lifecycle_id=workflow_lifecycle_id.strip(),
    )
