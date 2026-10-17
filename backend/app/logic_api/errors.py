class LogicApiError(Exception):
    """Base class for safe, typed Logic API failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LogicApiUnavailable(LogicApiError):
    """The upstream API could not be reached or returned a server error."""


class LogicInvalidRequest(LogicApiError):
    """The API rejected a request as invalid (HTTP 400)."""


class LogicConflict(LogicApiError):
    """The upstream API reported a conflict (HTTP 409)."""


class LogicDayClosed(LogicInvalidRequest):
    """The requested date is closed."""


class LogicOpeningHoursMissing(LogicInvalidRequest):
    """The API has no opening hours configured for the requested date."""


class LogicNotFound(LogicApiError):
    """The requested upstream resource does not exist."""


class LogicApiProtocolError(LogicApiError):
    """The API response did not match the documented data contract."""
