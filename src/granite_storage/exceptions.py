class StorageError(Exception):
    """Base storage exception."""


class ContentTooLargeError(StorageError):
    """Raised when streamed or in-memory content exceeds the configured limit."""
