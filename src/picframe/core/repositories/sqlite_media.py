"""
SQLite implementation of the IMediaRepository.

This module provides the concrete implementation for managing ephemeral
media metadata using a SQLite database (`media_cache.db3`).
"""

import logging
import sqlite3
from typing import Any

from picframe.core.repositories.interfaces import IMediaRepository
from picframe.core.repositories.migrations import Migration, MigrationManager

logger = logging.getLogger(__name__)

# Define the initial schema migration for media_cache.db3
MEDIA_MIGRATIONS = [
    Migration(
        version=1,
        up_script="""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            directory_id INTEGER NOT NULL,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            file_size INTEGER NOT NULL,
            last_modified REAL NOT NULL,
            width INTEGER,
            height INTEGER,
            orientation INTEGER DEFAULT 1,
            exif_datetime REAL,
            duration REAL,
            is_deleted INTEGER DEFAULT 0,
            created_at REAL DEFAULT (julianday('now')),
            updated_at REAL DEFAULT (julianday('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_media_directory ON media(directory_id);
        CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_deleted ON media(is_deleted);
        """,
    )
]


class SQLiteMediaRepository(IMediaRepository):
    """
    SQLite-backed repository for media metadata cache.

    This class manages the `media_cache.db3` database, ensuring thread-safe
    access and automatic schema migrations upon initialization.
    """

    def __init__(self, db_path: str) -> None:
        """
        Initialize the SQLiteMediaRepository.

        Args:
            db_path: The file path to the SQLite database.
        """
        self._db_path = db_path
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL;")

        # Run migrations
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Execute database migrations to ensure the schema is up-to-date."""
        manager = MigrationManager(self._conn, MEDIA_MIGRATIONS)
        manager.migrate()

    def add_media_item(self, media_data: dict[str, Any]) -> int:
        """
        Add a new media item to the cache.

        Args:
            media_data: A dictionary containing the media metadata.

        Returns:
            The ID of the newly inserted media item.
        """
        columns = ", ".join(media_data.keys())
        placeholders = ", ".join("?" for _ in media_data)
        query = f"INSERT INTO media ({columns}) VALUES ({placeholders})"
        
        with self._conn:
            cursor = self._conn.execute(query, tuple(media_data.values()))
            return cursor.lastrowid or 0

    def get_media_item(self, media_id: int) -> dict[str, Any] | None:
        """
        Retrieve a media item by its ID.

        Args:
            media_id: The ID of the media item to retrieve.

        Returns:
            A dictionary containing the media metadata, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM media WHERE id = ?", (media_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_media_item(self, media_id: int, updates: dict[str, Any]) -> None:
        """
        Update specific fields of an existing media item.

        Args:
            media_id: The ID of the media item to update.
            updates: A dictionary of fields to update.
        """
        if not updates:
            return

        # Automatically update the updated_at timestamp
        if "updated_at" not in updates:
            updates["updated_at"] = "julianday('now')"
            
        set_clause = ", ".join(
            f"{k} = ?" if k != "updated_at" else f"{k} = {v}" 
            for k, v in updates.items()
        )
        
        # Filter out the raw SQL values from the parameters
        params = tuple(v for k, v in updates.items() if k != "updated_at") + (media_id,)
        
        query = f"UPDATE media SET {set_clause} WHERE id = ?"
        
        with self._conn:
            self._conn.execute(query, params)

    def delete_media_item(self, media_id: int) -> None:
        """
        Mark a media item as deleted (soft delete).

        Args:
            media_id: The ID of the media item to delete.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE media SET is_deleted = 1, updated_at = julianday('now') "
                "WHERE id = ?",
                (media_id,),
            )

    def get_all_media(self) -> list[dict[str, Any]]:
        """
        Retrieve all active (non-deleted) media items.

        Returns:
            A list of dictionaries containing media metadata.
        """
        cursor = self._conn.execute("SELECT * FROM media WHERE is_deleted = 0")
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
