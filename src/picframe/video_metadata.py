"""
Video metadata handling module for picframe.
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime


@dataclass
class VideoMetadata:
    """
    A dataclass representing video metadata.

    Attributes:
    -----------
    width : int
        The width of the video in pixels.
    height : int
        The height of the video in pixels.
    duration : float
        The duration of the video in seconds.
    rotation : int
        The rotation angle of the video (e.g., 0, 90, 180, 270).
    title : Optional[str]
        The title of the video from metadata.
    caption : Optional[str]
        The caption/subtitle of the video.
    creation_date : Optional[datetime]
        The creation date of the video or file creation date as fallback.
    gps_coords : Optional[Tuple[float, float]]
        The GPS coordinates (latitude, longitude) where the video was taken.
    """
    width: int
    height: int
    duration: float
    rotation: int
    title: Optional[str] = None
    caption: Optional[str] = None
    creation_date: Optional[datetime] = None
    gps_coords: Optional[Tuple[float, float]] = None

    @property
    def is_portrait(self) -> bool:
        """Returns True if the video is in portrait orientation."""
        return self.rotation in [90, 270, -90, -270]

    @property
    def dimensions(self) -> tuple[int, int]:
        """Returns the (width, height) tuple, adjusted for rotation."""
        if self.is_portrait:
            return (self.height, self.width)
        return (self.width, self.height)

    @property
    def exif_datetime(self) -> float:
        """Returns the creation date as Unix timestamp for compatibility with image metadata."""
        return self.creation_date.timestamp() if self.creation_date else 0
