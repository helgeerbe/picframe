"""
Domain models for media items.

This module defines the core data structures representing media files
(images and videos) within the application.
"""

from dataclasses import dataclass
from enum import StrEnum


class MediaType(StrEnum):
    """Enumeration of supported media types."""

    IMAGE = "image"
    VIDEO = "video"


@dataclass
class MediaItem:
    """
    Represents a single media file and its associated metadata.

    This model is used to pass media information between the metadata
    extractors, the database repositories, and the playback engine.
    """

    filepath: str
    filename: str
    directory_id: int
    media_type: MediaType
    file_size: int
    last_modified: float
    width: int | None = None
    height: int | None = None
    orientation: int = 1
    exif_datetime: float | None = None
    f_number: float | None = None
    exposure_time: str | None = None
    iso: int | None = None
    focal_length: str | None = None
    make: str | None = None
    model: str | None = None
    lens: str | None = None
    rating: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    title: str | None = None
    caption: str | None = None
    tags: str | None = None
    is_portrait: bool | None = None
    location: str | None = None
    duration: float | None = None
    codec: str | None = None
    pixel_format: str | None = None
    framerate: float | None = None
    bitrate: int | None = None
    displayed_count: int = 0
    last_displayed: float = 0.0
    id: int | None = None
    is_deleted: bool = False

    def to_dict(self) -> dict[str, str | int | float | bool | None]:
        """
        Convert the MediaItem to a dictionary suitable for database insertion.

        Returns:
            A dictionary representation of the media item.
        """
        return {
            "id": self.id,
            "filepath": self.filepath,
            "filename": self.filename,
            "directory_id": self.directory_id,
            "media_type": self.media_type.value,
            "file_size": self.file_size,
            "last_modified": self.last_modified,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "exif_datetime": self.exif_datetime,
            "f_number": self.f_number,
            "exposure_time": self.exposure_time,
            "iso": self.iso,
            "focal_length": self.focal_length,
            "make": self.make,
            "model": self.model,
            "lens": self.lens,
            "rating": self.rating,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "title": self.title,
            "caption": self.caption,
            "tags": self.tags,
            "is_portrait": (
                int(self.is_portrait) if self.is_portrait is not None else None
            ),
            "location": self.location,
            "duration": self.duration,
            "codec": self.codec,
            "pixel_format": self.pixel_format,
            "framerate": self.framerate,
            "bitrate": self.bitrate,
            "displayed_count": self.displayed_count,
            "last_displayed": self.last_displayed,
            "is_deleted": int(self.is_deleted),
        }
