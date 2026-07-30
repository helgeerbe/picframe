"""
Interfaces for metadata extraction strategies.

This module defines the protocol for extracting metadata from different
types of media files (e.g., images, videos).
"""

from typing import Protocol

from picframe.core.models.media import MediaItem


class IMetadataStrategy(Protocol):
    """
    Protocol defining the interface for metadata extraction strategies.

    Implementations of this protocol are responsible for parsing specific
    file formats and populating a MediaItem object with the extracted data.
    """

    def extract(self, filepath: str, directory_id: int) -> MediaItem | None:
        """
        Extract metadata from a media file.

        Args:
            filepath: The absolute path to the media file.
            directory_id: The ID of the directory containing the file.

        Returns:
            A populated MediaItem object, or None if extraction fails
            or the file format is unsupported.
        """
        ...
