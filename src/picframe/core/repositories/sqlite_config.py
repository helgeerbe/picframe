"""
SQLite implementation of the IConfigRepository.

This module provides the concrete implementation for managing persistent
configuration data using a SQLite database (`config.db3`).
"""

import json
import logging
import sqlite3
import threading
from typing import Any

from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.repositories.migrations import Migration, MigrationManager

logger = logging.getLogger(__name__)

# The canonical keyword selector for the text overlay. Must match the seed in
# `default_config.yaml` and the `RendererConfig` DTO default.
_TEXT_OVERLAY_FORMAT_KEYWORDS = "title caption name date folder location"
_TEXT_OVERLAY_KEYWORDS = ("title", "caption", "name", "date", "folder", "location")


def _normalize_text_overlay_format_v2(conn: sqlite3.Connection) -> None:
    """Rewrite legacy strftime ``text_overlay_format`` values to keyword format.

    Picframe 1.x stored a strftime string (e.g. ``"%b %d, %Y"``) in
    ``viewer.text_overlay_format``. Picframe 2.0 expects a space-separated list
    of keywords (``title caption name date folder location``) and renders each
    element by matching the keywords in :func:`_generate_text_string`. A legacy
    strftime value matches none of the keywords, so the overlay is always
    empty. This migration rewrites such values to the canonical keyword string
    so existing installs show text again without requiring a manual re-toggle.
    Values that already contain keywords (user choices) are left untouched.

    The stored value may be JSON-encoded (picframe 2.0 repository, written via
    :func:`SQLiteConfigRepository.set_app_config`) or a plain string (picframe
    1.x legacy). Decode JSON when possible to inspect the logical value; the
    replacement is always written JSON-encoded so the repository can read it.
    """
    cursor = conn.execute(
        "SELECT value FROM app_config WHERE key = ?",
        ("viewer.text_overlay_format",),
    )
    row = cursor.fetchone()
    if row is None:
        return
    raw = row[0] if not isinstance(row, sqlite3.Row) else row["value"]
    if not isinstance(raw, str):
        return
    try:
        logical = json.loads(raw)
        if not isinstance(logical, str):
            return
    except (TypeError, json.JSONDecodeError):
        logical = raw
    lowered = logical.lower()
    has_keyword = any(kw in lowered for kw in _TEXT_OVERLAY_KEYWORDS)
    has_strftime = "%" in logical
    if has_strftime and not has_keyword:
        conn.execute(
            "UPDATE app_config SET value = ? WHERE key = ?",
            (json.dumps(_TEXT_OVERLAY_FORMAT_KEYWORDS), "viewer.text_overlay_format"),
        )
        logger.info(
            "Migrated legacy strftime text_overlay_format to keyword format: %r -> %r",
            logical,
            _TEXT_OVERLAY_FORMAT_KEYWORDS,
        )


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
    ),
    Migration(
        version=2,
        up_script=_normalize_text_overlay_format_v2,
    ),
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
        self._lock = threading.RLock()
        # Use check_same_thread=False because the repository is shared across
        # service threads. Access to the connection is serialized by _lock.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")

        # Run migrations
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Execute database migrations to ensure the schema is up-to-date."""
        with self._lock:
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
        with self._lock:
            cursor = self._conn.execute("SELECT value FROM app_config WHERE key = ?", (key,))
            row = cursor.fetchone()
        if row:
            if row["value"] is None:
                logger.warning(f"Config key has NULL value, using default: {key}")
                return default
            try:
                return json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                logger.error(f"Failed to decode JSON for config key: {key}")
                return default
        return default

    def get_app_config_bool(self, key: str, default: bool = False) -> bool:
        """
        Retrieve an application configuration value by key and ensure it is a boolean.

        Args:
            key: The configuration key to look up.
            default: The value to return if the key is not found or cannot be parsed.

        Returns:
            The boolean configuration value.
        """
        val = self.get_app_config(key, default)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "t", "y", "yes")
        return bool(val)

    def set_app_config(self, key: str, value: Any) -> None:
        """
        Set an application configuration value.

        The value is serialized to a JSON string before storage.

        Args:
            key: The configuration key to set.
            value: The value to store.
        """
        json_value = json.dumps(value)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO app_config (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json_value),
            )

    def delete_app_config_prefix(self, prefix: str) -> None:
        """
        Delete configuration values whose keys match a dotted section prefix.

        A prefix of ``hardware_inputs`` removes both a direct ``hardware_inputs``
        key and all nested ``hardware_inputs.*`` keys without touching similarly
        named sections such as ``hardware_inputs_extra``.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                DELETE FROM app_config
                WHERE key = ? OR key LIKE ?
                """,
                (prefix, f"{prefix}.%"),
            )

    def get_all_app_config(self) -> dict[str, Any]:
        """
        Retrieve all application configuration values.

        Returns:
            A dictionary containing all configuration key-value pairs.
        """
        with self._lock:
            cursor = self._conn.execute("SELECT key, value FROM app_config")
            rows = cursor.fetchall()
        config = {}
        for row in rows:
            if row["value"] is None:
                logger.warning(f"Skipping config key with NULL value: {row['key']}")
                continue
            try:
                config[row["key"]] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                logger.error(f"Failed to decode JSON for config key: {row['key']}")
        return config

    def get_all_directories(self) -> list[dict[str, Any]]:
        """
        Retrieve all configured media directories.

        Returns:
            A list of dictionaries containing directory information.
        """
        with self._lock:
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
        with self._lock, self._conn:
            cursor = self._conn.execute("INSERT INTO directories (path) VALUES (?)", (path,))
            return cursor.lastrowid or 0

    def remove_directory(self, directory_id: int) -> None:
        """
        Remove a media directory from monitoring.

        Args:
            directory_id: The ID of the directory to remove.
        """
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM directories WHERE id = ?", (directory_id,))

    def purge_orphaned_directories(self, active_directory_ids: set[int]) -> int:
        """
        Remove directory rows that are no longer referenced by active media.

        Args:
            active_directory_ids: The set of directory IDs still in use by
                non-deleted media rows in the media cache.

        Returns:
            The number of directory rows removed.
        """
        with self._lock, self._conn:
            cursor = self._conn.execute("SELECT id FROM directories")
            all_ids = {int(row["id"]) for row in cursor.fetchall()}

            if not active_directory_ids:
                # No directories are active — purge all rows in one statement.
                cursor = self._conn.execute("DELETE FROM directories")
                return cursor.rowcount

            orphan_ids = list(all_ids - active_directory_ids)
            if not orphan_ids:
                return 0

            batch_size = 999
            purged_count = 0
            for i in range(0, len(orphan_ids), batch_size):
                batch = orphan_ids[i : i + batch_size]
                placeholders = ",".join("?" * len(batch))
                cursor = self._conn.execute(
                    f"DELETE FROM directories WHERE id IN ({placeholders})", batch
                )
                purged_count += cursor.rowcount
            return purged_count

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
