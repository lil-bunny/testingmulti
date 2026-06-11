class DomainError(Exception):
    """Base for domain and application failures."""


class NotFoundError(DomainError):
    pass


class ForbiddenError(DomainError):
    pass


class UnauthorizedError(DomainError):
    pass


class AuthUnauthorizedError(UnauthorizedError):
    pass


class AuthServiceUnavailableError(DomainError):
    pass


class ValidationError(DomainError):
    pass
