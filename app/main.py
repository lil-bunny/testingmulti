from dotenv import load_dotenv

load_dotenv(override=False)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from app.api.exception_handlers import register_exception_handlers  # noqa: E402
from app.api.middleware.request_context import RequestContextMiddleware  # noqa: E402
from app.api.openapi import OPENAPI_TAGS  # noqa: E402
from app.api.v1 import v1_router  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service status")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        openapi_tags=OPENAPI_TAGS,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)


    @app.get(
        "/health",
        tags=["health"],
        summary="Health check",
        response_model=HealthResponse,
    )
    async def health():
        return HealthResponse(status="Running")


    app.include_router(v1_router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        logger.info("Starting Freight AI Platform")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Shutting down Freight AI Platform")

    return app


app = create_app()