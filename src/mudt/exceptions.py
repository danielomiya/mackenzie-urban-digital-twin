from __future__ import annotations


class IngestError(Exception):
    """Base class for all errors."""


class RetrievalError(IngestError):
    """Base class for errors raised while retrieving a source from upstream."""

    def __init__(self, message: str, *, retrieval_url: str) -> None:
        super().__init__(message)
        self.retrieval_url = retrieval_url


class UpstreamUnavailableError(RetrievalError):
    """Raised on a transient network or transport failure."""


class RetrievalAddressDeadError(RetrievalError):
    """Raised when a retrieval address has moved or been withdrawn (e.g. 404)."""


class NonDataResponseError(RetrievalError):
    """Raised when the upstream returns HTTP 200 with a non-data body (e.g. an HTML error page)."""


class InconsistentCRSError(IngestError):
    """Raised when a source declares no CRS, or one different from the configured native CRS."""


class AreaOfInterestMissingError(IngestError):
    """Raised when no committed area-of-interest file exists."""


class ConfigInvalidError(IngestError):
    """Raised when a configuration file fails validation."""

    def __init__(self, message: str, *, invalid_fields: list[str]) -> None:
        super().__init__(message)
        self.invalid_fields = invalid_fields
