from app.domain.error_catalog import ErrorCategory, ErrorCode, _CatalogError


class WorkflowException(Exception):
    """Raised when a business or domain rule fails inside a LangGraph node."""

    def __init__(self, error: ErrorCode | str, message: str | None = None):
        if isinstance(error, _CatalogError):
            self.error_code = error.value
            self.error_category = error.category
            self.message = message or error.description
        else:
            self.error_code = str(error)
            self.error_category = ErrorCategory.SYSTEM
            self.message = message or ErrorCategory.SYSTEM.value

        super().__init__(self.message)


class TenantResolutionError(Exception):
    """Raised when tenant resolution fails due to ambiguity or configuration issues."""
    pass