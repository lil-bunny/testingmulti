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

    @classmethod
    def from_wire(cls, code: str, message: str) -> SchedulingFailure:
        from app.domain.appointment_scheduling.skip_reasons import scheduling_failure_from_skip
        from app.domain.error_catalog import SystemError

        wire = str(code or "").strip()
        mapped = scheduling_failure_from_skip(wire)
        if mapped is not None:
            text = str(message or "").strip() or mapped.message
            return cls(code=mapped.code, message=text, category=mapped.category)
        return cls(
            code=wire or SystemError.UNEXPECTED_NODE_FAILURE.value,
            message=message or wire.replace("_", " "),
            category=SystemError.UNEXPECTED_NODE_FAILURE.category,
        )

    def to_workflow_exception(self) -> "WorkflowException":
        from app.domain.error_catalog import SystemError, resolve_error_code
        from app.exceptions import WorkflowException

        catalog = resolve_error_code(self.code)
        return WorkflowException(
            catalog or SystemError.UNEXPECTED_NODE_FAILURE,
            self.message,
        )


def raise_scheduling_result_failure(
    failure: SchedulingFailure | None,
    *,
    wire: str | None = None,
    message: str | None = None,
) -> None:
    """Raise catalog WorkflowException from a service failure DTO or wire code."""
    if failure is not None:
        raise failure.to_workflow_exception()
    text = str(message or wire or "").strip() or "unexpected failure"
    raise SchedulingFailure.from_wire(str(wire or ""), text).to_workflow_exception()


def raise_email_send_error(error: str | None) -> None:
    """Map draft/confirmation send outcomes to business vs integration catalog errors."""
    from app.domain.error_catalog import IntegrationError
    from app.exceptions import WorkflowException

    wire = str(error or "").strip()
    if wire in {"missing_mikey_account_id", "missing_email_draft", "missing_thread_or_tenant"}:
        raise SchedulingFailure.from_wire(wire, wire.replace("_", " ")).to_workflow_exception()
    raise WorkflowException(
        IntegrationError.EMAIL_SEND_FAILED,
        wire or IntegrationError.EMAIL_SEND_FAILED.description,
    )
