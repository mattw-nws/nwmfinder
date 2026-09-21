"""Exception hierarchy for nwmfinder."""


class NwmFinderError(Exception):
    """Base class for all nwmfinder errors."""


class DataNotFoundError(NwmFinderError):
    """Raised when no data could be located within the allowed rollback window."""


class UnexpectedResponseError(NwmFinderError):
    """Raised when a server returns a response code that isn't handled (after retries)."""


class DownloadError(NwmFinderError):
    """Base class for download-related failures."""


class IncompleteDownloadError(DownloadError):
    """Raised when a downloaded file's size never matched the server-reported size."""
