"""Scheduling failure DTO (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.error_catalog import ErrorCategory


@dataclass(frozen=True)
class SchedulingFailure:
    code: str
    message: str
    category: ErrorCategory

    @classmethod
    def from_catalog(
        cls,
        error: object,
        message: str,
    ) -> SchedulingFailure:
        from app.domain.error_catalog import _CatalogError

        if isinstance(error, _CatalogError):
            return cls(
                code=error.value,
                message=message,
                category=error.category,
            )
        return cls(
            code=str(error),
            message=message,
            category=ErrorCategory.SYSTEM,
        )

    def to_workflow_exception(self) -> "WorkflowException":
        from app.domain.error_catalog import SystemError, resolve_error_code
        from app.exceptions import WorkflowException

        catalog = resolve_error_code(self.code)
        return WorkflowException(
            catalog or SystemError.UNEXPECTED_NODE_FAILURE,
            self.message,
        )
