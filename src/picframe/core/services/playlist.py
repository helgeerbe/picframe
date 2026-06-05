"""
PlaylistManager service for querying and managing media playback order.

This module provides the `PlaylistManager` class, which interacts with the
`IMediaRepository` to fetch media items based on configuration filters,
handles shuffling logic, and maintains playback history.
"""

import logging
import os
import random
from typing import Any

from picframe.core.events.dto import FileChangeEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.models.media import DisplayItem, DisplayLayout, MediaItem, MediaType
from picframe.core.models.playlist import (
    PlaylistCriteria,
    SHUFFLE_MODE_FEWER_REPEATS,
    SHUFFLE_MODE_STANDARD,
    normalize_shuffle_mode,
)
from picframe.core.repositories.interfaces import IConfigRepository, IMediaRepository

logger = logging.getLogger(__name__)

_FILE_MTIME_TOLERANCE = 1e-6
_FEWER_REPEATS_CANDIDATES = 12


class PlaylistManager:
    """
    Manages the selection and ordering of media items for playback.

    The PlaylistManager is responsible for querying the media repository,
    applying filters (e.g., date ranges, tags), shuffling the results,
    and providing the next media item to be displayed.
    """

    def __init__(
        self,
        media_repository: IMediaRepository,
        config_repository: IConfigRepository | None = None,
        event_publisher: IEventPublisher | None = None,
    ) -> None:
        """
        Initialize the PlaylistManager.

        Args:
            media_repository: The repository used to access media metadata.
        """
        self._media_repo = media_repository
        self._config_repo = config_repository
        self._event_publisher = event_publisher
        self._playlist: list[dict[str, Any]] = []
        self._display_playlist: list[list[dict[str, Any]]] = []
        self._history: list[list[dict[str, Any]]] = []
        self._current_index: int = -1
        self._shuffle: bool = True
        self._shuffle_mode: str = SHUFFLE_MODE_STANDARD
        self._run_through_count: int = 0
        self._reshuffle_num: int = 1
        self._portrait_pairs: bool = False

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
        if self._config_repo is not None:
            criteria = self._get_playlist_criteria(shuffle)
            self._shuffle = criteria.shuffle
            self._shuffle_mode = normalize_shuffle_mode(criteria.shuffle_mode)
            self._playlist = self._media_repo.query_media(criteria)
        else:
            self._playlist = self._media_repo.get_all_media()
            if self._shuffle:
                random.shuffle(self._playlist)
            self._shuffle_mode = SHUFFLE_MODE_STANDARD
            self._portrait_pairs = False

        self._display_playlist = self._build_display_playlist(self._playlist)
        if self._shuffle and self._shuffle_mode == SHUFFLE_MODE_FEWER_REPEATS:
            self._display_playlist = self._shuffle_fewer_repeats(self._display_playlist)

        if not self._display_playlist:
            logger.warning("No media items found to build playlist.")
            self._current_index = -1
            return

        self._run_through_count = 0
        self._current_index = 0
        logger.info(
            "Playlist built with %s media items and %s display slots.",
            len(self._playlist),
            len(self._display_playlist),
        )

    def get_next(self) -> DisplayItem | None:
        """
        Get the next display item in the playlist.
        Skips items whose files no longer exist on disk.

        Returns:
            The next DisplayItem, or a placeholder display item if the
            playlist is empty or all files are missing.
        """
        if not self._display_playlist:
            self.build_playlist(shuffle=self._shuffle)
            if not self._display_playlist:
                return DisplayItem.single(self._get_no_images_placeholder())

        attempts = 0
        max_attempts = len(self._display_playlist)

        while attempts < max_attempts:
            if self._current_index >= len(self._display_playlist):
                self._advance_playlist_cycle()
                if not self._display_playlist:
                    return DisplayItem.single(self._get_no_images_placeholder())
                max_attempts = max(max_attempts, len(self._display_playlist))

            slot_data = self._display_playlist[self._current_index]
            self._current_index += 1
            attempts += 1
            
            prepared_slot = self._prepare_slot_for_display(slot_data)
            if prepared_slot:
                self._history.append(prepared_slot)
                return self._slot_to_display_item(prepared_slot)

        return DisplayItem.single(self._get_no_images_placeholder())

    def get_current(self) -> DisplayItem | None:
        """
        Get the currently playing display item.
        
        Returns:
            The current DisplayItem, or None if no item is playing.
        """
        if not self._history:
            return None
            
        # Fetch latest data so geocoding and display stats stay fresh.
        current_slot = self._history[-1]
        fresh_slot: list[dict[str, Any]] = []
        for item_data in current_slot:
            media_id = item_data.get("id")
            if media_id:
                latest_data = self._media_repo.get_media_item(media_id)
                if latest_data and isinstance(latest_data, dict):
                    fresh_slot.append(latest_data)
                    continue
            fresh_slot.append(item_data)

        self._history[-1] = fresh_slot
        return self._slot_to_display_item(fresh_slot)

    def delete_current(
        self,
        target: str = "left",
        media_ids: list[int] | None = None,
    ) -> list[int]:
        """
        Mark selected current media items as deleted in the repository.

        Args:
            target: One of "left", "right", or "both".
            media_ids: Optional current media IDs selected by the UI.

        Returns:
            The deleted media IDs. An empty list means validation failed or
            there was no current item.
        """
        selected_ids = self.resolve_current_delete_ids(target, media_ids)
        for media_id in selected_ids:
            self._media_repo.delete_media_item(media_id)
        return selected_ids

    def delete_media_ids(self, media_ids: list[int]) -> None:
        """Remove specific media IDs from the cache after user delete moved files."""
        for media_id in media_ids:
            self._media_repo.remove_media_item(media_id)

    def resolve_current_delete_ids(
        self,
        target: str = "left",
        media_ids: list[int] | None = None,
    ) -> list[int]:
        """Resolve and validate delete IDs against the current display item."""
        current = self.get_current()
        if current is None or current.id == 0:
            return []

        current_ids = [
            int(item.id)
            for item in current.items
            if item.id is not None and item.id != 0
        ]
        if not current_ids:
            return []

        if current.layout == DisplayLayout.SINGLE:
            selected_ids = [current_ids[current.primary_index]]
        else:
            if target == "left":
                selected_ids = [current_ids[0]]
            elif target == "right" and len(current_ids) > 1:
                selected_ids = [current_ids[1]]
            elif target == "both":
                selected_ids = list(current_ids)
            else:
                return []

        if media_ids is not None:
            requested = [int(media_id) for media_id in media_ids]
            if sorted(requested) != sorted(selected_ids):
                logger.warning(
                    "Rejecting stale or mismatched delete payload. requested=%s current=%s target=%s",
                    requested,
                    current_ids,
                    target,
                )
                return []

        return selected_ids
            
    def purge_missing_files(self) -> int:
        """
        Purge missing files from the repository.
        
        Returns:
            The number of purged records.
        """
        return self._media_repo.purge_missing_files()

    def get_previous(self) -> DisplayItem | None:
        """
        Get the previously played display item from history.
        Skips items whose files no longer exist on disk.

        Returns:
            The previous DisplayItem, or None if history is empty.
        """
        while len(self._history) >= 2:
            # Remove current item from history
            self._history.pop()
            # Get the previous item (now the last item in history)
            slot_data = self._history[-1]
            
            # Adjust current index so get_next() works correctly
            # after get_previous()
            if self._current_index > 0:
                self._current_index -= 1

            prepared_slot = self._prepare_slot_for_display(slot_data)
            if prepared_slot:
                self._history[-1] = prepared_slot
                return self._slot_to_display_item(prepared_slot)
            else:
                logger.warning("Previous display slot has no existing files, skipping.")
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

    def _advance_playlist_cycle(self) -> None:
        """Loop or reshuffle when the current playlist has been exhausted."""
        self._run_through_count += 1
        if self._shuffle and self._run_through_count >= self._reshuffle_num:
            self.build_playlist(shuffle=self._shuffle)
        else:
            self._current_index = 0

    def _get_playlist_criteria(self, shuffle_override: bool | None = None) -> PlaylistCriteria:
        """Build playlist criteria from the live configuration repository."""
        assert self._config_repo is not None

        def config_value(key: str, default: Any) -> Any:
            return self._config_repo.get_app_config(key, default)

        def config_bool(key: str, default: bool) -> bool:
            if hasattr(self._config_repo, "get_app_config_bool"):
                return self._config_repo.get_app_config_bool(key, default)
            value = config_value(key, default)
            if isinstance(value, str):
                return value.lower() in {"1", "true", "yes", "on"}
            return bool(value)

        self._reshuffle_num = max(1, int(config_value("model.reshuffle_num", 1) or 1))
        shuffle = config_bool("model.shuffle", self._shuffle)
        if shuffle_override is not None:
            shuffle = shuffle_override
        self._portrait_pairs = config_bool("model.portrait_pairs", False)
        shuffle_mode = normalize_shuffle_mode(
            config_value("model.shuffle_mode", SHUFFLE_MODE_STANDARD)
        )

        return PlaylistCriteria(
            pic_dir=str(config_value("model.pic_dir", "~/Pictures")),
            subdirectory=str(config_value("model.subdirectory", "")),
            date_from=config_value("model.date_from", ""),
            date_to=config_value("model.date_to", ""),
            location_filter=str(config_value("model.location_filter", "")),
            tags_filter=str(config_value("model.tags_filter", "")),
            shuffle=shuffle,
            shuffle_mode=shuffle_mode,
            sort_cols=str(config_value("model.sort_cols", "fname ASC")),
            recent_n=int(config_value("model.recent_n", 0) or 0),
        )

    def _build_display_playlist(
        self,
        playlist: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """Build display slots from raw playlist rows."""
        if not self._portrait_pairs:
            return [[item] for item in playlist]

        portrait_rows = [item for item in playlist if self._is_pairable_portrait(item)]
        portrait_index = 0
        skip_portrait_slot = False
        display_playlist: list[list[dict[str, Any]]] = []

        for item in playlist:
            if not self._is_pairable_portrait(item):
                display_playlist.append([item])
                continue

            if skip_portrait_slot:
                skip_portrait_slot = False
                continue

            if portrait_index >= len(portrait_rows):
                continue

            slot = [portrait_rows[portrait_index]]
            portrait_index += 1
            if portrait_index < len(portrait_rows):
                slot.append(portrait_rows[portrait_index])
                portrait_index += 1
                skip_portrait_slot = True
            display_playlist.append(slot)

        return display_playlist

    def _shuffle_fewer_repeats(
        self,
        display_playlist: list[list[dict[str, Any]]],
    ) -> list[list[dict[str, Any]]]:
        """Choose a random order that keeps recently displayed slots later."""
        if len(display_playlist) <= 1:
            return list(display_playlist)

        best_candidate: list[list[dict[str, Any]]] | None = None
        best_score: float | None = None

        for _ in range(_FEWER_REPEATS_CANDIDATES):
            candidate = list(display_playlist)
            random.shuffle(candidate)
            score = self._score_fewer_repeats_candidate(candidate)
            if best_candidate is None or best_score is None or score > best_score:
                best_candidate = candidate
                best_score = score

        return best_candidate or list(display_playlist)

    @classmethod
    def _score_fewer_repeats_candidate(
        cls,
        display_playlist: list[list[dict[str, Any]]],
    ) -> float:
        """Higher score means recently displayed slots appear later."""
        last_displayed_values = [cls._slot_last_displayed(slot) for slot in display_playlist]
        displayed_values = [value for value in last_displayed_values if value > 0]
        if not displayed_values:
            return 0.0

        oldest = min(displayed_values)
        newest = max(displayed_values)
        count = len(last_displayed_values)
        score = 0.0

        for index, last_displayed in enumerate(last_displayed_values):
            if last_displayed <= 0:
                recency_penalty = 0.0
            elif newest <= oldest:
                recency_penalty = 1.0
            else:
                recency_penalty = (last_displayed - oldest) / (newest - oldest)
            early_weight = (count - index) / count
            score -= early_weight * recency_penalty

        return score

    @staticmethod
    def _slot_last_displayed(slot: list[dict[str, Any]]) -> float:
        """Return the newest display timestamp represented by a display slot."""
        values: list[float] = []
        for item in slot:
            try:
                values.append(float(item.get("last_displayed") or 0.0))
            except (TypeError, ValueError):
                values.append(0.0)
        return max(values, default=0.0)

    @staticmethod
    def _is_pairable_portrait(item: dict[str, Any]) -> bool:
        """Return True when a row can participate in a portrait pair."""
        return (
            str(item.get("media_type", "image")).lower() == MediaType.IMAGE.value
            and bool(item.get("is_portrait"))
        )

    def _prepare_slot_for_display(
        self,
        slot_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop unavailable/stale files, refresh metadata, and record display stats."""
        prepared_slot: list[dict[str, Any]] = []

        for item_data in slot_data:
            media_id = item_data.get("id")
            if media_id:
                latest_data = self._media_repo.get_media_item(media_id)
                if latest_data and isinstance(latest_data, dict):
                    item_data = latest_data

            if item_data.get("is_deleted"):
                continue

            filepath = item_data.get("filepath")
            file_stat = self._get_display_file_stat(str(filepath) if filepath else "")
            if file_stat is None:
                logger.warning(f"File not found, marking inactive and skipping: {filepath}")
                if media_id:
                    self._media_repo.delete_media_item(media_id)
                continue

            if self._file_has_changed(item_data, file_stat):
                logger.info(f"File changed before display, requesting reindex and skipping: {filepath}")
                if filepath:
                    self._request_reindex(str(filepath))
                continue

            if media_id:
                updated_data = self._media_repo.record_media_displayed(media_id)
                if updated_data and isinstance(updated_data, dict):
                    item_data = updated_data

            prepared_slot.append(item_data)

        return prepared_slot

    @staticmethod
    def _get_display_file_stat(filepath: str) -> os.stat_result | None:
        if not filepath or not os.path.isfile(filepath):
            return None
        try:
            return os.stat(filepath)
        except OSError:
            return None

    @staticmethod
    def _file_has_changed(item_data: dict[str, Any], file_stat: os.stat_result) -> bool:
        try:
            stored_size = int(item_data.get("file_size", -1))
            stored_mtime = float(item_data.get("last_modified", -1.0))
        except (TypeError, ValueError):
            return True
        return (
            stored_size != int(file_stat.st_size)
            or abs(stored_mtime - float(file_stat.st_mtime)) > _FILE_MTIME_TOLERANCE
        )

    def _request_reindex(self, filepath: str) -> None:
        if self._event_publisher is not None:
            self._event_publisher.publish(
                FileChangeEvent(event_type="modified", path=filepath)
            )

    def _slot_to_display_item(self, slot_data: list[dict[str, Any]]) -> DisplayItem:
        """Convert one display slot from repository rows to a DisplayItem."""
        items = [self._dict_to_media_item(item) for item in slot_data]
        if (
            len(items) == 2
            and all(item.media_type == MediaType.IMAGE for item in items)
            and all(item.is_portrait for item in items)
        ):
            return DisplayItem.portrait_pair(items[0], items[1])
        return DisplayItem.single(items[0])

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
