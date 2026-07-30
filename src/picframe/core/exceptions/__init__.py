"""
Custom exception hierarchy for the Picframe application.
"""


class PicframeError(Exception):
    """Base exception for all custom Picframe errors."""

    pass


class SystemError(PicframeError):
    """Critical system-level errors that may require a restart."""

    pass


class MediaProcessingError(PicframeError):
    """
    Errors that occur during media processing (e.g., corrupted file).
    These are typically recoverable by skipping the file.
    """

    pass
