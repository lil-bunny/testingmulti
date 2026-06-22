"""Version 1 HTTP API routes."""

from fastapi import APIRouter

from app.api.v1.shipments import router as shipments_router
from app.api.v1.workflow_lifecycles import router as workflow_lifecycles_router

v1_router = APIRouter()
v1_router.include_router(shipments_router)
v1_router.include_router(workflow_lifecycles_router)
