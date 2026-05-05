"""Pydantic Logfire wiring.

`configure_observability(app)` is called once from `app.main` and:
- configures Logfire with the token from settings (no-op if token is missing),
- instruments the FastAPI app, httpx (Turvo + LLM HTTP calls),
  psycopg (Postgres / langgraph checkpointer), and pydantic validations.

Instrumenting auxiliary libraries is wrapped in try/except so a missing optional
extra never breaks app startup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logger import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = get_logger(__name__)

_CONFIGURED = False


def configure_observability(app: "FastAPI") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    if not settings.LOGFIRE_TOKEN:
        logger.info("LOGFIRE_TOKEN not set; skipping Logfire instrumentation")
        return

    try:
        import logfire
    except ImportError:
        logger.warning("logfire not installed; skipping instrumentation")
        return

    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=settings.LOGFIRE_SERVICE_NAME,
        environment=settings.ENV,
    )

    try:
        logfire.instrument_fastapi(app)
    except Exception:
        logger.exception("Failed to instrument FastAPI for Logfire")

    try:
        logfire.instrument_httpx()
    except Exception:
        logger.exception("Failed to instrument httpx for Logfire")

    try:
        logfire.instrument_psycopg()
    except Exception:
        logger.exception("Failed to instrument psycopg for Logfire")

    try:
        logfire.instrument_pydantic()
    except Exception:
        logger.exception("Failed to instrument pydantic for Logfire")

    _CONFIGURED = True
    logger.info(
        "Logfire instrumentation enabled (service=%s env=%s)",
        settings.LOGFIRE_SERVICE_NAME,
        settings.ENV,
    )
