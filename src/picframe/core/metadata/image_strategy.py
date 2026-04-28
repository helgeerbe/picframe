"""
Image metadata extraction strategy.

This module implements the IMetadataStrategy for image files, utilizing
PIL (Pillow) and exifread to extract dimensions, orientation, and EXIF data.
"""

import logging
import os
from datetime import datetime

import exifread
from PIL import Image, UnidentifiedImageError

from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.models.media import MediaItem, MediaType

logger = logging.getLogger(__name__)


class ImageMetadataStrategy(IMetadataStrategy):
    """
    Strategy for extracting metadata from image files.

    This class handles parsing image dimensions, orientation, and EXIF
    creation dates. It gracefully handles missing or corrupted EXIF data.
    """

    def extract(self, filepath: str, directory_id: int) -> MediaItem | None:
        """
        Extract metadata from an image file.

        Args:
            filepath: The absolute path to the image file.
            directory_id: The ID of the directory containing the file.

        Returns:
            A populated MediaItem object, or None if extraction fails.
        """
        if not os.path.isfile(filepath):
            logger.warning(f"File not found: {filepath}")
            return None

        try:
            file_stat = os.stat(filepath)
            file_size = file_stat.st_size
            last_modified = file_stat.st_mtime
            filename = os.path.basename(filepath)

            width, height = self._get_dimensions(filepath)
            orientation = self._get_orientation(filepath)
            exif_datetime = self._get_exif_datetime(filepath)

            return MediaItem(
                filepath=filepath,
                filename=filename,
                directory_id=directory_id,
                media_type=MediaType.IMAGE,
                file_size=file_size,
                last_modified=last_modified,
                width=width,
                height=height,
                orientation=orientation,
                exif_datetime=exif_datetime,
            )
        except Exception as e:
            logger.error(f"Failed to extract metadata from {filepath}: {e}")
            return None

    def _get_dimensions(self, filepath: str) -> tuple[int | None, int | None]:
        """
        Retrieve the width and height of the image using PIL.

        Args:
            filepath: The path to the image file.

        Returns:
            A tuple of (width, height), or (None, None) if parsing fails.
        """
        try:
            with Image.open(filepath) as img:
                return img.width, img.height
        except UnidentifiedImageError:
            logger.warning(f"Could not identify image format: {filepath}")
            return None, None
        except Exception as e:
            logger.warning(f"Error reading dimensions for {filepath}: {e}")
            return None, None

    def _get_orientation(self, filepath: str) -> int:
        """
        Retrieve the EXIF orientation tag.

        Args:
            filepath: The path to the image file.

        Returns:
            The orientation integer (1-8), defaulting to 1 (normal).
        """
        try:
            with open(filepath, "rb") as f:
                tags = exifread.process_file(f, details=False, stop_tag="Image Orientation")
                if "Image Orientation" in tags:
                    val = tags["Image Orientation"].values
                    if isinstance(val, list) and len(val) > 0:
                        return int(val[0])
        except Exception as e:
            logger.debug(f"Error reading orientation for {filepath}: {e}")
        return 1

    def _get_exif_datetime(self, filepath: str) -> float | None:
        """
        Retrieve the EXIF DateTimeOriginal tag and convert to a timestamp.

        Args:
            filepath: The path to the image file.

        Returns:
            The Unix timestamp of the creation date, or None if not found.
        """
        try:
            with open(filepath, "rb") as f:
                tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
                if "EXIF DateTimeOriginal" in tags:
                    date_str = str(tags["EXIF DateTimeOriginal"])
                    # EXIF format: YYYY:MM:DD HH:MM:SS
                    dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    return dt.timestamp()
        except ValueError:
            logger.debug(f"Invalid EXIF date format in {filepath}")
        except Exception as e:
            logger.debug(f"Error reading EXIF date for {filepath}: {e}")
        return None
