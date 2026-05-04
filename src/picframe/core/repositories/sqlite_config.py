"""
SQLite implementation of the IConfigRepository.

This module provides the concrete implementation for managing persistent
configuration data using a SQLite database (`config.db3`).
"""

import json
import logging
import sqlite3
from typing import Any

from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.repositories.migrations import Migration, MigrationManager

logger = logging.getLogger(__name__)

# Define the initial schema migration for config.db3
CONFIG_MIGRATIONS = [
    Migration(
        version=1,
        up_script="""
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL
        );
        """,
    )
]


class SQLiteConfigRepository(IConfigRepository):
    """
    SQLite-backed repository for application configuration.

    This class manages the `config.db3` database, ensuring thread-safe
    access and automatic schema migrations upon initialization.
    """

    def __init__(self, db_path: str) -> None:
        """
        Initialize the SQLiteConfigRepository.

        Args:
            db_path: The file path to the SQLite database (e.g., 'config.db3').
        """
        self._db_path = db_path
        # Use check_same_thread=False because we might share the connection
        # across threads, but we will rely on SQLite's internal locking or
        # explicit locks if needed. For simple CRUD, SQLite handles concurrency
        # well if configured correctly.
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
        manager = MigrationManager(self._conn, CONFIG_MIGRATIONS)
        manager.migrate()

    def get_app_config(self, key: str, default: Any = None) -> Any:
        """
        Retrieve an application configuration value by key.

        The value is stored as a JSON string in the database and deserialized
        upon retrieval.

        Args:
            key: The configuration key to look up.
            default: The value to return if the key is not found.

        Returns:
            The deserialized configuration value, or the default if not found.
        """
        cursor = self._conn.execute(
            "SELECT value FROM app_config WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON for config key: {key}")
                return default
        return default

    def set_app_config(self, key: str, value: Any) -> None:
        """
        Set an application configuration value.

        The value is serialized to a JSON string before storage.

        Args:
            key: The configuration key to set.
            value: The value to store.
        """
        json_value = json.dumps(value)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO app_config (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json_value),
            )

    def get_all_app_config(self) -> dict[str, Any]:
        """
        Retrieve all application configuration values.

        Returns:
            A dictionary containing all configuration key-value pairs.
        """
        cursor = self._conn.execute("SELECT key, value FROM app_config")
        config = {}
        for row in cursor.fetchall():
            try:
                config[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON for config key: {row['key']}")
        return config

    def get_all_directories(self) -> list[dict[str, Any]]:
        """
        Retrieve all configured media directories.

        Returns:
            A list of dictionaries containing directory information.
        """
        cursor = self._conn.execute("SELECT id, path FROM directories")
        return [dict(row) for row in cursor.fetchall()]

    def add_directory(self, path: str) -> int:
        """
        Add a new media directory to monitor.

        Args:
            path: The absolute path to the directory.

        Returns:
            The ID of the newly inserted directory.
        """
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO directories (path) VALUES (?)", (path,)
            )
            return cursor.lastrowid or 0

    def remove_directory(self, directory_id: int) -> None:
        """
        Remove a media directory from monitoring.

        Args:
            directory_id: The ID of the directory to remove.
        """
        with self._conn:
            self._conn.execute(
                "DELETE FROM directories WHERE id = ?", (directory_id,)
            )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
