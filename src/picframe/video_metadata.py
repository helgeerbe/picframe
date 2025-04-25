from dataclasses import dataclass
from typing import Optional

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
    """
    width: int
    height: int
    duration: float
    rotation: int

    @property
    def is_portrait(self) -> bool:
        """Returns True if the video is in portrait orientation."""
        return self.rotation in [90, 270, -90, -270]

    @property
    def dimensions(self) -> tuple[int, int]:
        """Returns the (width, height) tuple."""
        return (self.width, self.height)
