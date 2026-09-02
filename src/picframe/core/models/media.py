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


class DisplayLayout(StrEnum):
    """Enumeration of slideshow display layouts."""

    SINGLE = "single"
    PORTRAIT_PAIR = "portrait_pair"


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

    def to_dict(self) -> dict[str, object]:
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
            "is_portrait": (int(self.is_portrait) if self.is_portrait is not None else None),
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


@dataclass
class DisplayItem:
    """
    Represents one slideshow slot.

    A display item may contain a single media item or two portrait image items.
    The first item is the primary item for backward-compatible metadata and
    delete semantics.
    """

    layout: DisplayLayout
    items: list[MediaItem]
    primary_index: int = 0

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("DisplayItem requires at least one media item")
        if self.primary_index < 0 or self.primary_index >= len(self.items):
            raise ValueError("DisplayItem primary_index is out of range")
        if self.layout == DisplayLayout.PORTRAIT_PAIR:
            if len(self.items) != 2:
                raise ValueError("Portrait pair display items require exactly two items")
            if any(item.media_type != MediaType.IMAGE for item in self.items):
                raise ValueError("Portrait pairs can only contain image media")
        elif len(self.items) != 1:
            raise ValueError("Single display items require exactly one item")

    @classmethod
    def single(cls, item: MediaItem) -> "DisplayItem":
        """Create a single-media display item."""
        return cls(layout=DisplayLayout.SINGLE, items=[item])

    @classmethod
    def portrait_pair(cls, left: MediaItem, right: MediaItem) -> "DisplayItem":
        """Create a two-image portrait-pair display item."""
        return cls(layout=DisplayLayout.PORTRAIT_PAIR, items=[left, right])

    @property
    def primary(self) -> MediaItem:
        """Return the primary media item."""
        return self.items[self.primary_index]

    @property
    def filepath(self) -> str:
        """Backward-compatible primary filepath."""
        return self.primary.filepath

    @property
    def filename(self) -> str:
        """Backward-compatible primary filename."""
        return self.primary.filename

    @property
    def id(self) -> int | None:
        """Backward-compatible primary media ID."""
        return self.primary.id

    @property
    def media_type(self) -> MediaType:
        """Backward-compatible primary media type."""
        return self.primary.media_type

    def to_dict(self) -> dict[str, object]:
        """Return a payload with primary fields plus display layout data."""
        primary_data = self.primary.to_dict()
        primary_data["layout"] = self.layout.value
        primary_data["primary_index"] = self.primary_index
        primary_data["items"] = [
            {
                **item.to_dict(),
                "role": "left" if index == 0 else "right",
                "index": index,
            }
            for index, item in enumerate(self.items)
        ]
        return primary_data
