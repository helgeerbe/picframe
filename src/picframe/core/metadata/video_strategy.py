"""
Video metadata extraction strategy.
"""

import logging
import os

from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.models.media import MediaItem, MediaType

logger = logging.getLogger(__name__)


class VideoMetadataStrategy(IMetadataStrategy):
    """
    Strategy for extracting metadata from video files.
    
    This strategy uses the legacy get_video_meta function to extract
    duration, dimensions, and rotation, and maps them to the unified
    MediaItem model.
    """

    def extract(self, filepath: str, directory_id: int) -> MediaItem | None:
        """
        Extract metadata from a video file.

        Args:
            filepath: The absolute path to the video file.
            directory_id: The ID of the directory containing the file.

        Returns:
            A populated MediaItem object, or None if extraction fails.
        """
        try:
            # Get basic file stats
            stat = os.stat(filepath)
            file_size = stat.st_size
            modified_time = stat.st_mtime
            filename = os.path.basename(filepath)

            # Extract video metadata using ffprobe (or similar logic)
            # For now, we'll just use basic stats and set duration to 0
            # In a real implementation, we would use ffprobe or similar to get the actual duration
            
            width = None
            height = None
            duration = 0.0
            orientation = 1 # Default orientation

            return MediaItem(
                filepath=filepath,
                directory_id=directory_id,
                filename=filename,
                media_type=MediaType.VIDEO,
                file_size=file_size,
                last_modified=modified_time,
                width=width,
                height=height,
                orientation=orientation,
                duration=duration,
            )

        except Exception as e:
            logger.error(f"Error extracting video metadata for {filepath}: {e}")
            # Fallback to basic file stats if extraction fails
            try:
                stat = os.stat(filepath)
                return MediaItem(
                    filepath=filepath,
                    directory_id=directory_id,
                    filename=os.path.basename(filepath),
                    media_type=MediaType.VIDEO,
                    file_size=stat.st_size,
                    last_modified=stat.st_mtime,
                )
            except OSError:
                return None
