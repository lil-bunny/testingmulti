from fastapi import FastAPI
from app.api.routes import router
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        docs_url="/docs"
    )

    @app.get("/")
    async def welcome():
        return "Welcome to Freightx"

    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    async def startup():
        logger.info("Starting Freight AI Platform")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Shutting down Freight AI Platform")

    return app


app = create_app()