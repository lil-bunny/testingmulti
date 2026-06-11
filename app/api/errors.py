from typing import Any

from fastapi import HTTPException


def error_content(
    code: str,
    message: str,
    *,
    details: Any | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return body


def http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_content(code, message, details=details),
        headers=headers,
    )
