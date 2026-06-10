"""v1 shipment endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import (
    get_current_user,
    get_tenant_slug_for_user,
    require_turvo_oauth_linked_for_slug,
)
from app.core.logger import get_logger
from app.domain.api_user import ApiUser
from app.services.pod_manual_upload_ingress_service import (
    PodLifecycleNotFoundError,
    PodManualUploadIngressService,
)
from app.services.pod_tms_upload_service import PodTmsUploadService

router = APIRouter(prefix="/shipments", tags=["shipments-v1"])
logger = get_logger(__name__)


class PodUploadQueuedResponse(BaseModel):
    success: bool = True
    shipment_id: str
    execution_id: str
    workflow_lifecycle_id: str
    message: str
    object_key: str | None = None
    document_id: str | None = None


@router.post(
    "/{shipment_id}/upload_pod",
    response_model=PodUploadQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue POD processing workflow for a shipment",
    description=(
        "``shipment_id`` is ``shipments.id`` (UUID primary key), not Turvo shipment number."
    ),
)
async def upload_pod(
    shipment_id: str,
    user: Annotated[ApiUser, Depends(get_current_user)],
    tenant_slug: Annotated[str, Depends(get_tenant_slug_for_user)],
    _: Annotated[str, Depends(require_turvo_oauth_linked_for_slug)],
    file: UploadFile = File(...),
) -> PodUploadQueuedResponse:
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PDF files are supported",
        )

    pdf_bytes = await file.read()
    try:
        PodTmsUploadService.validate_pdf(pdf_bytes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    uploaded_by = str(user.email).strip() if user.email else None
    uploaded_by_user_id = str(user.id).strip() if user.id else None

    try:
        result = PodManualUploadIngressService().enqueue(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id.strip(),
            pdf_bytes=pdf_bytes,
            filename=file.filename or None,
            uploaded_by=uploaded_by or None,
            uploaded_by_user_id=uploaded_by_user_id or None,
        )
    except PodLifecycleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e) or "pod_lifecycle not found for shipment",
        ) from e
    except RuntimeError as e:
        logger.exception("upload_pod staging failed shipment_id=%s", shipment_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    return PodUploadQueuedResponse(
        shipment_id=result.shipment_id,
        execution_id=result.execution_id,
        workflow_lifecycle_id=result.workflow_lifecycle_id,
        message="workflow queued",
        object_key=result.object_key,
        document_id=result.document_id,
    )
