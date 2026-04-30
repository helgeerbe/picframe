"""
Repository interfaces for the Picframe application.

This module defines the abstract protocols for data access, adhering to the
Dependency Inversion Principle. It provides interfaces for both the persistent
configuration database and the ephemeral media cache database.
"""

from typing import Any, Protocol


class IConfigRepository(Protocol):
    """
    Protocol defining the data access methods for persistent configuration.
    
    This repository manages application settings, monitored directories,
    and MQTT configuration.
    """

    def get_app_config(self, key: str, default: Any = None) -> Any:
        """
        Retrieve an application configuration value by key.

        Args:
            key: The configuration key to look up.
            default: The value to return if the key is not found.

        Returns:
            The configuration value, or the default if not found.
        """
        ...

    def set_app_config(self, key: str, value: Any) -> None:
        """
        Set an application configuration value.

        Args:
            key: The configuration key to set.
            value: The value to store.
        """
        ...

    def get_all_directories(self) -> list[dict[str, Any]]:
        """
        Retrieve all configured media directories.

        Returns:
            A list of dictionaries containing directory information.
        """
        ...

    def add_directory(self, path: str) -> int:
        """
        Add a new media directory to monitor.

        Args:
            path: The absolute path to the directory.

        Returns:
            The ID of the newly inserted directory.
        """
        ...

    def remove_directory(self, directory_id: int) -> None:
        """
        Remove a media directory from monitoring.

        Args:
            directory_id: The ID of the directory to remove.
        """
        ...


class IMediaRepository(Protocol):
    """
    Protocol defining the data access methods for the ephemeral media cache.
    
    This repository manages metadata for images and videos, as well as
    playlist definitions.
    """

    def add_media_item(self, media_data: dict[str, Any]) -> int:
        """
        Add a new media item to the cache.

        Args:
            media_data: A dictionary containing the media metadata.

        Returns:
            The ID of the newly inserted media item.
        """
        ...

    def get_media_item(self, media_id: int) -> dict[str, Any] | None:
        """
        Retrieve a media item by its ID.

        Args:
            media_id: The ID of the media item to retrieve.

        Returns:
            A dictionary containing the media metadata, or None if not found.
        """
        ...

    def update_media_item(
        self, media_id: int, updates: dict[str, Any]
    ) -> None:
        """
        Update specific fields of an existing media item.

        Args:
            media_id: The ID of the media item to update.
            updates: A dictionary of fields to update.
        """
        ...

    def delete_media_item(self, media_id: int) -> None:
        """
        Mark a media item as deleted (soft delete) or remove it.

        Args:
            media_id: The ID of the media item to delete.
        """
        ...

    def get_all_media(self) -> list[dict[str, Any]]:
        """
        Retrieve all active (non-deleted) media items.

        Returns:
            A list of dictionaries containing media metadata.
        """
        ...

    def purge_missing_files(self) -> int:
        """
        Scan the database and remove entries for files that no longer exist on disk.

        Returns:
            The number of records deleted.
        """
        ...
