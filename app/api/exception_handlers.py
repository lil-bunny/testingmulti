from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.errors import error_content
from app.domain.auth_errors import (
    DomainError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def _detail_to_body(detail: object) -> dict:
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return detail
    message = str(detail) if detail is not None else "Request failed"
    return error_content("http_error", message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        body = _detail_to_body(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_content(
                "validation_error",
                "Request validation failed",
                details=exc.errors(),
            ),
        )

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=error_content("not_found", str(exc)),
        )

    @app.exception_handler(UnauthorizedError)
    async def unauthorized(_: Request, exc: UnauthorizedError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=error_content("unauthorized", str(exc)),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(ForbiddenError)
    async def forbidden(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content=error_content("forbidden", str(exc)),
        )

    @app.exception_handler(ValidationError)
    async def validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_content("validation_error", str(exc)),
        )

    @app.exception_handler(DomainError)
    async def domain(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_content("domain_error", str(exc)),
        )
