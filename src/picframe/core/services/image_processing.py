"""
ImageProcessingService for handling image manipulation tasks.

This module provides the `ImageProcessingService` class, which is responsible
for resizing and caching generated image artifacts, as well as providing an
asynchronous worker pool for metadata extraction.
"""

import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.models.media import MediaItem

logger = logging.getLogger(__name__)


class ImageProcessingService:
    """
    Service for processing images before display.

    Handles tasks such as resizing to fit the screen, managing the processed
    image cache, and extracting metadata asynchronously. Renderer-only visual
    effects such as matting are applied in the render image-preparation path.
    """

    def __init__(self, cache_dir: str = "/tmp/picframe_cache", max_workers: int = 4) -> None:
        """
        Initialize the ImageProcessingService.

        Args:
            cache_dir: The directory to store processed images.
            max_workers: Maximum number of threads for the worker pool.
        """
        self._cache_dir = Path(cache_dir)
        self._paused = False
        self._ensure_cache_dir()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ImageProcessingWorker"
        )

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

    def extract_metadata_async(
        self,
        filepath: str,
        directory_id: int,
        strategy: IMetadataStrategy,
        callback: Callable[[MediaItem | None], None] | None = None
    ) -> "Future[MediaItem | None]":  # type: ignore[type-arg]
        """
        Extract metadata from a file asynchronously using the worker pool.

        Args:
            filepath: The path to the media file.
            directory_id: The ID of the directory containing the file.
            strategy: The metadata extraction strategy to use.
            callback: Optional callback function to execute when extraction completes.
                      It receives the extracted MediaItem (or None) as its argument.

        Returns:
            A Future object representing the asynchronous execution.
        """
        if self._paused:
            logger.debug(f"Skipping metadata extraction while paused: {filepath}")
            future: Future[MediaItem | None] = Future()
            future.set_result(None)
            if callback:
                callback(None)
            return future

        def _extract_task() -> MediaItem | None:
            try:
                logger.debug(f"Extracting metadata for {filepath}")
                result = strategy.extract(filepath, directory_id)
                if callback:
                    callback(result)
                return result
            except Exception as e:
                logger.error(f"Error extracting metadata for {filepath}: {e}")
                if callback:
                    callback(None)
                return None

        return self._executor.submit(_extract_task)

    def pause(self) -> None:
        """Pause acceptance of new asynchronous processing tasks."""
        self._paused = True

    def resume(self) -> None:
        """Resume acceptance of new asynchronous processing tasks."""
        self._paused = False

    def clear_cache(self) -> None:
        """Remove all files from the cache directory."""
        logger.info(f"Clearing image cache: {self._cache_dir}")
        try:
            for item in self._cache_dir.iterdir():
                if item.is_file():
                    item.unlink()
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the worker pool.
        
        Args:
            wait: If True, wait for all pending tasks to complete.
        """
        logger.info("Shutting down ImageProcessingService worker pool")
        self._executor.shutdown(wait=wait)
