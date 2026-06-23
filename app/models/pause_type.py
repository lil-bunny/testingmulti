"""Typed ``workflow_lifecycles.pause_type`` values."""

from __future__ import annotations

from enum import StrEnum

from app.domain.error_catalog import ErrorCategory


class PauseType(StrEnum):
    """Why a workflow lifecycle is paused awaiting review/intervention."""

    SYSTEM_ERROR = "system_error"
    BUSINESS_EXCEPTION = "business_exception"

    @classmethod
    def from_error_category(cls, category: ErrorCategory | str | None) -> PauseType:
        """Map an :class:`ErrorCategory` (or wire string) to a pause type.

        ``BUSINESS`` maps to :attr:`BUSINESS_EXCEPTION`; ``INTEGRATION``, ``SYSTEM``,
        and any unknown value fall back to :attr:`SYSTEM_ERROR`.
        """
        if category is None:
            return cls.SYSTEM_ERROR
        try:
            resolved = (
                category
                if isinstance(category, ErrorCategory)
                else ErrorCategory(str(category))
            )
        except ValueError:
            return cls.SYSTEM_ERROR
        if resolved is ErrorCategory.BUSINESS:
            return cls.BUSINESS_EXCEPTION
        return cls.SYSTEM_ERROR
