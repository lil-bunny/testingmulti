import asyncio
from dotenv import load_dotenv
from fastapi.responses import JSONResponse

load_dotenv(override=False)

from fastapi import FastAPI, status
from app.api.routes import router
from app.api.user_turvo import router as user_turvo_router
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

    @app.get("/test")
    async def aws_ecs_test():
        logger.info("AWS ECS health check")
        await asyncio.sleep(60)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "OK"},
        )

    @app.get("/health", summary="Health check (returns 'Running')")
    async def health():
        return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "Running"},
    )


    app.include_router(router, prefix="/api")
    app.include_router(user_turvo_router, prefix="/api")

    # configure_observability(app)

    @app.on_event("startup")
    async def startup():
        logger.info("Starting Freight AI Platform")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Shutting down Freight AI Platform")

    return app


app = create_app()