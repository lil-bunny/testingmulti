"""v1 workflow-lifecycle review endpoints (acknowledge / resolve)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Security, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.api.security import portal_bearer
from app.core.logger import get_logger
from app.domain.api_user import ApiUser
from app.services.workflow_review_service import (
    WorkflowLifecycleNotFoundError,
    WorkflowReviewService,
)

router = APIRouter(prefix="/workflow-lifecycles", tags=["workflow-lifecycles"])
logger = get_logger(__name__)


class ReviewCommentRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=4000, description="Review comment")


class ReviewAcknowledgeResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    workflow_lifecycle_id: str = Field(..., description="Workflow lifecycle identifier")
    workflow_name: str = Field(..., description="Workflow name")
    activity_log_id: str = Field(..., description="Activity log identifier")


class ReviewResolveResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    workflow_lifecycle_id: str = Field(..., description="Workflow lifecycle identifier")
    workflow_name: str = Field(..., description="Workflow name")
    activity_log_ids: list[str] = Field(..., description="Activity log identifiers")
    to_status: str = Field(..., description="Resulting status")
    to_sub_status: str = Field(..., description="Resulting sub-status")


@router.post(
    "/{workflow_lifecycle_id}/acknowledge",
    response_model=ReviewAcknowledgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge review",
    dependencies=[Security(portal_bearer)],
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        422: {"description": "Unprocessable entity"},
    },
)
async def acknowledge_review(
    workflow_lifecycle_id: Annotated[
        str,
        Path(description="Workflow lifecycle identifier (UUID)"),
    ],
    body: Annotated[ReviewCommentRequest, Body()],
    user: Annotated[ApiUser, Depends(get_current_user)],
) -> ReviewAcknowledgeResponse:
    workflow_review_service = WorkflowReviewService()
    try:
        result = workflow_review_service.acknowledge(
            workflow_lifecycle_id=workflow_lifecycle_id.strip(),
            comment=body.comment,
            user=user,
        )
    except WorkflowLifecycleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        logger.exception(
            "workflow_review_acknowledge failed workflow_lifecycle_id=%s",
            workflow_lifecycle_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    return ReviewAcknowledgeResponse(
        workflow_lifecycle_id=result.workflow_lifecycle_id,
        workflow_name=result.workflow_name,
        activity_log_id=result.activity_log_id,
    )


@router.post(
    "/{workflow_lifecycle_id}/resolve",
    response_model=ReviewResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve review",
    dependencies=[Security(portal_bearer)],
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        422: {"description": "Unprocessable entity"},
    },
)
async def resolve_review(
    workflow_lifecycle_id: Annotated[
        str,
        Path(description="Workflow lifecycle identifier (UUID)"),
    ],
    body: Annotated[ReviewCommentRequest, Body()],
    user: Annotated[ApiUser, Depends(get_current_user)],
) -> ReviewResolveResponse:
    workflow_review_service = WorkflowReviewService()
    try:
        result = workflow_review_service.resolve(
            workflow_lifecycle_id=workflow_lifecycle_id.strip(),
            comment=body.comment,
            user=user,
        )
    except WorkflowLifecycleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        logger.exception(
            "workflow_review_resolve failed workflow_lifecycle_id=%s",
            workflow_lifecycle_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    return ReviewResolveResponse(
        workflow_lifecycle_id=result.workflow_lifecycle_id,
        workflow_name=result.workflow_name,
        activity_log_ids=result.activity_log_ids,
        to_status=result.to_status,
        to_sub_status=result.to_sub_status,
    )
