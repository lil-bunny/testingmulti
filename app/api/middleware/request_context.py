import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logger import get_logger
from app.core.request_context import (
    bind_request_id,
    bind_request_state_from_context,
    clear_request_context,
)

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        clear_request_context()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        bind_request_id(request_id)
        bind_request_state_from_context(request)
        start = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception(
                "request_failed method=%s path=%s",
                request.method,
                request.url.path,
            )
            clear_request_context()
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_completed method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            status_code,
            elapsed_ms,
        )
        response.headers["X-Request-Id"] = request_id
        clear_request_context()
        return response
