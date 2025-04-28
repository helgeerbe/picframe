"""
Video metadata handling module for picframe.
"""
from typing import Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class VideoMetadata:
    """
    Represents metadata for a video file, including dimensions, duration, rotation,
    and additional optional fields for parity with image EXIF metadata.

    Attributes:
        width (int): The width of the video in pixels.
        height (int): The height of the video in pixels.
        duration (float): The duration of the video in seconds.
        rotation (int): The rotation of the video in degrees (e.g., 0, 90, 180, 270).
        title (Optional[str]): The title of the video, if available.
        caption (Optional[str]): The caption or description of the video, if available.
        creation_date (Optional[datetime]): The creation date of the video.
        gps_coords (Optional[Tuple[float, float]]): The GPS coordinates where the video was recorded.
        f_number (Optional[Any]): The f-number (aperture) of the camera used to record the video.
        make (Optional[str]): The make (manufacturer) of the camera used to record the video.
        model (Optional[str]): The model of the camera used to record the video.
        exposure_time (Optional[Any]): The exposure time of the camera used to record the video.
        iso (Optional[Any]): The ISO sensitivity of the camera used to record the video.
        focal_length (Optional[Any]): The focal length of the lens used to record the video.
        rating (Optional[Any]): The rating of the video, if available.
        lens (Optional[str]): The lens used to record the video, if available.
        tags (Optional[Any]): Tags or keywords associated with the video.

    Properties:
        is_portrait (bool): Indicates whether the video is in portrait orientation.
        dimensions (tuple[int, int]): The dimensions of the video as a (width, height) tuple, 
            adjusted for rotation.
        exif_datetime (Optional[float]): The creation date as a Unix timestamp, for compatibility 
            with image metadata.
    """
    width: int
    height: int
    duration: float
    rotation: int
    title: Optional[str] = None
    caption: Optional[str] = None
    creation_date: Optional[datetime] = None
    gps_coords: Optional[Tuple[float, float]] = None
    # --- new fields for parity with image EXIF ---
    f_number: Optional[Any] = None
    make: Optional[str] = None
    model: Optional[str] = None
    exposure_time: Optional[Any] = None
    iso: Optional[Any] = None
    focal_length: Optional[Any] = None
    rating: Optional[Any] = None
    lens: Optional[str] = None
    tags: Optional[Any] = None

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
    def exif_datetime(self) -> Optional[float]:
        """Returns the creation date as Unix timestamp for compatibility with image metadata."""
        return self.creation_date.timestamp() if self.creation_date else None
