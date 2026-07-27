"""Scheduling failure DTO (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.error_catalog import (
    BusinessError,
    ErrorCategory,
    ErrorCode,
    IntegrationError,
    SystemError,
    format_error_message,
    resolve_error_code,
)
from app.exceptions import WorkflowException
from app.integrations.ascend.errors import AscendError, resolve_ascend_error


@dataclass(frozen=True)
class SchedulingFailure:
    code: str
    message: str
    category: ErrorCategory

    @classmethod
    def from_catalog(
        cls,
        error: ErrorCode,
        message: str | None = None,
        **context: str,
    ) -> SchedulingFailure:
        text = message if message is not None else format_error_message(error, **context)
        return cls(
            code=error.value,
            message=text,
            category=error.category,
        )

    @classmethod
    def from_ascend(
        cls,
        error: AscendError,
        message: str | None = None,
        **context: str,
    ) -> SchedulingFailure:
        if message is not None:
            text = message
        else:

            class _SafeFormatMap(dict[str, str]):
                def __missing__(self, key: str) -> str:
                    return ""

            text = error.description.format_map(_SafeFormatMap(context))
        return cls(
            code=error.value,
            message=text,
            category=error.category,
        )

    @classmethod
    def from_wire(cls, code: str, message: str = "") -> SchedulingFailure:
        wire = str(code or "").strip()
        catalog = resolve_error_code(wire)
        if catalog is not None:
            text = str(message or "").strip() or format_error_message(catalog)
            return cls.from_catalog(catalog, text)
        ascend = resolve_ascend_error(wire)
        if ascend is not None:
            text = str(message or "").strip()
            return cls.from_ascend(ascend, text or None)
        return cls.from_catalog(
            SystemError.UNEXPECTED_NODE_FAILURE,
            str(message or "").strip() or wire.replace("_", " ") or SystemError.UNEXPECTED_NODE_FAILURE.description,
        )

    def to_workflow_exception(self) -> WorkflowException:
        catalog = resolve_error_code(self.code)
        if catalog is not None:
            return WorkflowException(catalog, self.message)
        return WorkflowException(self.code, self.message, category=self.category)


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
    wire = str(error or "").strip()
    if wire in {
        BusinessError.MISSING_MIKEY_ACCOUNT_ID.value,
        BusinessError.SCHEDULING_DRAFT_NOT_READY.value,
    }:
        raise SchedulingFailure.from_wire(wire).to_workflow_exception()
    raise WorkflowException(
        IntegrationError.EMAIL_SEND_FAILED,
        wire or IntegrationError.EMAIL_SEND_FAILED.description,
    )
