"""
ImageProcessingService for handling image manipulation tasks.

This module provides the `ImageProcessingService` class, which is responsible
for resizing, matting, and caching images for display.
"""

import logging
import os
from pathlib import Path

from PIL import Image, ImageOps

from picframe.core.models.media import MediaItem

logger = logging.getLogger(__name__)


class ImageProcessingService:
    """
    Service for processing images before display.

    Handles tasks such as resizing to fit the screen, applying matting
    (borders/shadows), and managing the processed image cache.
    """

    def __init__(self, cache_dir: str = "/tmp/picframe_cache") -> None:
        """
        Initialize the ImageProcessingService.

        Args:
            cache_dir: The directory to store processed images.
        """
        self._cache_dir = Path(cache_dir)
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Ensure the cache directory exists."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(
                f"Failed to create cache directory {self._cache_dir}: {e}"
            )

    def process_image(
        self,
        media_item: MediaItem,
        target_width: int,
        target_height: int,
        fit: bool = True,
    ) -> str | None:
        """
        Process an image for display.

        This method resizes the image to the target dimensions and saves it
        to the cache directory.

        Args:
            media_item: The MediaItem to process.
            target_width: The desired width.
            target_height: The desired height.
            fit: If True, scale to fit within dimensions
                 (maintaining aspect ratio).
                 If False, crop to fill dimensions.

        Returns:
            The path to the processed image in the cache,
            or None if processing fails.
        """
        if not media_item.filepath or not os.path.exists(media_item.filepath):
            logger.error(f"Image file not found: {media_item.filepath}")
            return None

        # Generate a cache filename based on the original path and target
        # dimensions. In a real implementation, this should probably use a
        # hash of the file path and modification time to handle updates.
        safe_name = media_item.filename.replace("/", "_").replace("\\", "_")
        cache_filename = f"{target_width}x{target_height}_{fit}_{safe_name}"
        cache_path = self._cache_dir / cache_filename

        # If the cached file already exists, return it
        if cache_path.exists():
            logger.debug(f"Returning cached image: {cache_path}")
            return str(cache_path)

        try:
            logger.info(f"Processing image: {media_item.filepath}")
            with Image.open(media_item.filepath) as img_file:
                # Apply EXIF orientation
                img: Image.Image = ImageOps.exif_transpose(img_file)
                
                # Convert to RGB if necessary (e.g., for RGBA or P modes)
                if img.mode != "RGB":
                    img = img.convert("RGB")

                target_size = (target_width, target_height)

                if fit:
                    # Scale to fit within the target dimensions,
                    # maintaining aspect ratio
                    img.thumbnail(target_size, Image.Resampling.LANCZOS)
                else:
                    # Crop to fill the target dimensions
                    img = ImageOps.fit(
                        img, target_size, Image.Resampling.LANCZOS
                    )

                # Save to cache
                img.save(cache_path, format="JPEG", quality=90)
                logger.debug(f"Saved processed image to cache: {cache_path}")
                
                return str(cache_path)

        except Exception as e:
            logger.error(f"Failed to process image {media_item.filepath}: {e}")
            return None

    def clear_cache(self) -> None:
        """Remove all files from the cache directory."""
        logger.info(f"Clearing image cache: {self._cache_dir}")
        try:
            for item in self._cache_dir.iterdir():
                if item.is_file():
                    item.unlink()
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
