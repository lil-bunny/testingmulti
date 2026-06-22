import asyncio
from dotenv import load_dotenv
from fastapi.responses import JSONResponse

load_dotenv(override=False)

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.routes import router
from app.api.user_turvo import router as user_turvo_router
from app.api.v1 import v1_router
from app.core.config import settings
from app.core.logger import get_logger
from app.core.observability import configure_observability

logger = get_logger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        docs_url="/docs"
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


    @app.get("/health", summary="Health check (returns 'Running')")
    async def health():
        return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "Running"},
    )


    app.include_router(router, prefix="/api")
    app.include_router(user_turvo_router, prefix="/api")
    app.include_router(v1_router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        logger.info("Starting Freight AI Platform")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Shutting down Freight AI Platform")

    return app


app = create_app()