class DomainError(ValueError):
    """A client-correctable error in a financial operation."""


class NotFoundError(DomainError):
    """Raised when a referenced financial entity does not exist."""
