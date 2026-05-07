"""
PlaylistManager service for querying and managing media playback order.

This module provides the `PlaylistManager` class, which interacts with the
`IMediaRepository` to fetch media items based on configuration filters,
handles shuffling logic, and maintains playback history.
"""

import logging
import random
from typing import Any

from picframe.core.models.media import MediaItem, MediaType
from picframe.core.repositories.interfaces import IMediaRepository

logger = logging.getLogger(__name__)


class PlaylistManager:
    """
    Manages the selection and ordering of media items for playback.

    The PlaylistManager is responsible for querying the media repository,
    applying filters (e.g., date ranges, tags), shuffling the results,
    and providing the next media item to be displayed.
    """

    def __init__(self, media_repository: IMediaRepository) -> None:
        """
        Initialize the PlaylistManager.

        Args:
            media_repository: The repository used to access media metadata.
        """
        self._media_repo = media_repository
        self._playlist: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._current_index: int = -1
        self._shuffle: bool = True

    def build_playlist(self, shuffle: bool | None = None) -> None:
        """
        Query the repository and build the active playlist.

        Args:
            shuffle: Whether to randomize the order of the playlist.
                     If None, uses the previous setting.
        """
        if shuffle is not None:
            self._shuffle = shuffle
            
        logger.info("Building new playlist...")
        # For now, we just get all active media.
        # In the future, this will incorporate filtering logic based on config.
        self._playlist = self._media_repo.get_all_media()
        
        if not self._playlist:
            logger.warning("No media items found to build playlist.")
            self._current_index = -1
            return

        if self._shuffle:
            random.shuffle(self._playlist)
            
        self._current_index = 0
        logger.info(f"Playlist built with {len(self._playlist)} items.")

    def get_next(self) -> MediaItem | None:
        """
        Get the next media item in the playlist.
        Skips items whose files no longer exist on disk.

        Returns:
            The next MediaItem, or a placeholder if the playlist is empty
            or all files are missing.
        """
        import os
        
        if not self._playlist:
            self.build_playlist(shuffle=self._shuffle)
            if not self._playlist:
                return self._get_no_images_placeholder()

        original_index = self._current_index
        looped = False

        while True:
            if self._current_index >= len(self._playlist):
                # Rebuild/reshuffle when we reach the end
                self.build_playlist(shuffle=self._shuffle)
                if not self._playlist:
                    return self._get_no_images_placeholder()
                # If we've rebuilt and still can't find a file after a
                # full pass, break
                if looped:
                    return self._get_no_images_placeholder()
                looped = True

            item_data = self._playlist[self._current_index]
            self._current_index += 1
            
            # Check if file exists
            filepath = item_data.get("filepath")
            if filepath and os.path.isfile(filepath):
                # Fetch latest data to ensure we have updated metadata (like geocoding)
                media_id = item_data.get("id")
                if media_id:
                    latest_data = self._media_repo.get_media_item(media_id)
                    if latest_data and isinstance(latest_data, dict):
                        item_data = latest_data
                        
                self._history.append(item_data)
                return self._dict_to_media_item(item_data)
            else:
                logger.warning(f"File not found, skipping: {filepath}")
                
            # Prevent infinite loop if all files in a non-empty playlist
            # are missing
            if looped and self._current_index == original_index:
                return self._get_no_images_placeholder()

    def get_current(self) -> MediaItem | None:
        """
        Get the currently playing media item.
        
        Returns:
            The current MediaItem, or None if no item is playing.
        """
        if not self._history:
            return None
            
        # Fetch the latest data from the repository to ensure we have updated metadata (like geocoding)
        current_item = self._history[-1]
        media_id = current_item.get("id")
        if media_id:
            latest_data = self._media_repo.get_media_item(media_id)
            if latest_data:
                # Update history with latest data
                self._history[-1] = latest_data
                return self._dict_to_media_item(latest_data)
                
        return self._dict_to_media_item(current_item)

    def delete_current(self) -> None:
        """
        Mark the current media item as deleted in the repository.
        """
        if not self._history:
            return
            
        current_item = self._history[-1]
        media_id = current_item.get("id")
        if media_id:
            self._media_repo.delete_media_item(media_id)
            
    def purge_missing_files(self) -> int:
        """
        Purge missing files from the repository.
        
        Returns:
            The number of purged records.
        """
        return self._media_repo.purge_missing_files()

    def get_previous(self) -> MediaItem | None:
        """
        Get the previously played media item from history.
        Skips items whose files no longer exist on disk.

        Returns:
            The previous MediaItem, or None if history is empty.
        """
        import os
        
        while len(self._history) >= 2:
            # Remove current item from history
            self._history.pop()
            # Get the previous item (now the last item in history)
            item_data = self._history[-1]
            
            # Adjust current index so get_next() works correctly
            # after get_previous()
            if self._current_index > 0:
                self._current_index -= 1
                
            # Check if file exists
            filepath = item_data.get("filepath")
            if filepath and os.path.isfile(filepath):
                # Fetch latest data to ensure we have updated metadata (like geocoding)
                media_id = item_data.get("id")
                if media_id:
                    latest_data = self._media_repo.get_media_item(media_id)
                    if latest_data and isinstance(latest_data, dict):
                        item_data = latest_data
                        
                return self._dict_to_media_item(item_data)
            else:
                logger.warning(
                    f"Previous file not found, skipping: {filepath}"
                )
                # Continue loop to try the next previous item
                
        return None

    def _get_no_images_placeholder(self) -> MediaItem:
        """
        Returns a placeholder MediaItem when no images are available.
        """
        import os
        
        # First try to find it in the user's configuration directory
        user_dir = os.path.expanduser("~/.picframe")
        user_no_pic_path = os.path.join(user_dir, "data", "no_pictures.jpg")
        
        if os.path.exists(user_no_pic_path):
            no_pic_path = user_no_pic_path
        else:
            # Fallback to the source code directory
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            no_pic_path = os.path.join(base_dir, "data", "no_pictures.jpg")
        
        return MediaItem(
            id=0,
            filepath=no_pic_path,
            filename="no_pictures.jpg",
            directory_id=0,
            media_type=MediaType.IMAGE,
            file_size=0,
            last_modified=0.0,
            width=0,
            height=0,
            orientation=1,
            is_deleted=False
        )

    def _dict_to_media_item(self, data: dict[str, Any]) -> MediaItem:
        """
        Convert a dictionary from the repository into a MediaItem domain model.

        Args:
            data: The dictionary containing media metadata.

        Returns:
            A populated MediaItem instance.
        """
        # Extract enum value
        media_type_str = data.get("media_type", "image")
        media_type = MediaType(media_type_str)
        
        # Create a copy to avoid modifying the original dict
        kwargs = dict(data)
        kwargs["media_type"] = media_type
        
        # Handle boolean conversion for is_portrait
        if "is_portrait" in kwargs and kwargs["is_portrait"] is not None:
            kwargs["is_portrait"] = bool(kwargs["is_portrait"])
            
        # Handle boolean conversion for is_deleted
        if "is_deleted" in kwargs and kwargs["is_deleted"] is not None:
            kwargs["is_deleted"] = bool(kwargs["is_deleted"])
            
        import dataclasses
        
        # Remove fields that are not part of the MediaItem dataclass
        # (e.g., created_at, updated_at from the database schema)
        valid_keys = {f.name for f in dataclasses.fields(MediaItem)}
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_keys}
        
        return MediaItem(**filtered_kwargs)
