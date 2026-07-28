"""v1 shipment endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, Security, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import (
    get_current_user,
    get_tenant_slug_for_user,
    require_turvo_oauth_linked_for_slug,
)
from app.api.security import portal_bearer
from app.core.logger import get_logger
from app.domain.api_user import ApiUser
from app.services.pod_lifecycle.manual_upload_ingress_service import (
    PodLifecycleNotFoundError,
    PodManualUploadIngressService,
)
from app.services.pod_lifecycle.tms_upload_service import (
    PodDocumentNotFoundError,
    PodTmsUploadService,
)

router = APIRouter(prefix="/shipments", tags=["shipments"])
logger = get_logger(__name__)


class PodUploadQueuedResponse(BaseModel):
    success: bool = Field(True, description="Whether the request was accepted")
    shipment_id: str = Field(..., description="Shipment identifier")
    execution_id: str = Field(..., description="Async job identifier")
    workflow_lifecycle_id: str = Field(..., description="Workflow lifecycle identifier")
    message: str = Field(..., description="Status message")
    object_key: str | None = Field(None, description="Stored file reference, if applicable")
    document_id: str | None = Field(None, description="Document identifier, if applicable")
    source: Literal["upload", "stored"] | None = Field(
        None,
        description="Whether the POD came from the request upload or existing storage",
    )


@router.post(
    "/{shipment_id}/upload_pod",
    response_model=PodUploadQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue POD upload",
    dependencies=[Security(portal_bearer)],
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        422: {"description": "Unprocessable entity"},
        503: {"description": "Service unavailable"},
    },
)
async def upload_pod(
    shipment_id: Annotated[str, Path(description="Shipment identifier (UUID)")],
    user: Annotated[ApiUser, Depends(get_current_user)],
    tenant_slug: Annotated[str, Depends(get_tenant_slug_for_user)],
    _: Annotated[str, Depends(require_turvo_oauth_linked_for_slug)],
    file: Annotated[
        UploadFile | None,
        File(description="PDF proof of delivery"),
    ] = None,
) -> PodUploadQueuedResponse:
    pdf_bytes: bytes | None = None
    filename: str | None = None
    if file is not None:
        content_type = (file.content_type or "").lower()
        if content_type and content_type not in (
            "application/pdf",
            "application/octet-stream",
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only PDF files are supported",
            )

        pdf_bytes = await file.read()
        filename = file.filename or None
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
            filename=filename,
            uploaded_by=uploaded_by or None,
            uploaded_by_user_id=uploaded_by_user_id or None,
        )
    except PodLifecycleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e) or "pod_lifecycle not found for shipment",
        ) from e
    except PodDocumentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
            or "No POD document on file for this shipment; upload a PDF or wait for email ingestion",
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
        source=result.source,
    )
