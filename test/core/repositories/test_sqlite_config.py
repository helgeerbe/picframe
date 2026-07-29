"""
Unit tests for the SQLiteConfigRepository.

This module verifies the CRUD operations for application configuration
and directory management using an in-memory SQLite database.
"""

import json
import sqlite3
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from picframe.core.repositories.sqlite_config import SQLiteConfigRepository


@pytest.fixture
def config_repo() -> Generator[SQLiteConfigRepository, None, None]:
    """Provide an in-memory SQLiteConfigRepository for testing."""
    # Using :memory: creates a new database in RAM
    repo = SQLiteConfigRepository(":memory:")
    yield repo
    repo.close()


def test_repository_initialization_runs_migrations(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Test that initializing the repository creates the required tables."""
    # Access the underlying connection to verify tables
    cursor = config_repo._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    assert "app_config" in tables
    assert "directories" in tables
    assert "schema_version" in tables


def test_set_and_get_app_config(config_repo: SQLiteConfigRepository) -> None:
    """Test storing and retrieving configuration values."""
    # Test string
    config_repo.set_app_config("theme", "dark")
    assert config_repo.get_app_config("theme") == "dark"

    # Test integer
    config_repo.set_app_config("delay", 10)
    assert config_repo.get_app_config("delay") == 10

    # Test dictionary (JSON serialization)
    complex_val = {"nested": True, "list": [1, 2, 3]}
    config_repo.set_app_config("complex", complex_val)
    assert config_repo.get_app_config("complex") == complex_val


def test_get_app_config_default(config_repo: SQLiteConfigRepository) -> None:
    """Test retrieving a non-existent key returns the default value."""
    assert config_repo.get_app_config("missing_key", "default_val") == "default_val"
    assert config_repo.get_app_config("missing_key") is None


def test_null_app_config_value_uses_default_and_is_skipped(
    tmp_path: Path,
) -> None:
    """Test existing databases with NULL config values do not crash reads."""
    db_path = tmp_path / "config.db3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE app_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL
        );
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT INTO schema_version (version) VALUES (1);
        INSERT INTO app_config (key, value) VALUES ('viewer.display_x', NULL);
        """
    )
    conn.close()

    repo = SQLiteConfigRepository(str(db_path))
    try:
        assert repo.get_app_config("viewer.display_x", 0) == 0
        assert "viewer.display_x" not in repo.get_all_app_config()
    finally:
        repo.close()


def test_get_app_config_serializes_shared_connection_access(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Concurrent config reads must not enter the sqlite connection together."""

    class EmptyCursor:
        def fetchone(self) -> None:
            return None

    class ContentionDetectingConnection:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._active_queries = 0

        def execute(self, *_args: object) -> EmptyCursor:
            should_raise = False
            with self._lock:
                self._active_queries += 1
                should_raise = self._active_queries > 1
            try:
                time.sleep(0.02)
                if should_raise:
                    raise sqlite3.InterfaceError("concurrent sqlite connection use")
                return EmptyCursor()
            finally:
                with self._lock:
                    self._active_queries -= 1

        def close(self) -> None:
            pass

    original_conn = config_repo._conn
    fake_conn = ContentionDetectingConnection()
    config_repo._conn = fake_conn  # type: ignore[assignment]
    original_conn.close()
    start = threading.Barrier(8)

    def read_clock_format() -> str:
        start.wait()
        return str(config_repo.get_app_config("viewer.clock_format", "%H:%M"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _index: read_clock_format(), range(8)))

    assert values == ["%H:%M"] * 8


def test_update_existing_app_config(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Test updating an existing configuration key."""
    config_repo.set_app_config("key1", "initial")
    config_repo.set_app_config("key1", "updated")
    assert config_repo.get_app_config("key1") == "updated"


def test_delete_app_config_prefix_only_removes_matching_section(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Test deleting a dotted config section without removing similar prefixes."""
    config_repo.set_app_config("hardware_inputs.enabled", True)
    config_repo.set_app_config("hardware_inputs.inputs.motion.type", "pir")
    config_repo.set_app_config("hardware_inputs_extra.enabled", True)
    config_repo.set_app_config("viewer.fps", 30)

    config_repo.delete_app_config_prefix("hardware_inputs")

    all_config = config_repo.get_all_app_config()
    assert "hardware_inputs.enabled" not in all_config
    assert "hardware_inputs.inputs.motion.type" not in all_config
    assert all_config["hardware_inputs_extra.enabled"] is True
    assert all_config["viewer.fps"] == 30


def test_add_and_get_directories(config_repo: SQLiteConfigRepository) -> None:
    """Test adding and retrieving media directories."""
    dir_id1 = config_repo.add_directory("/path/to/photos")
    dir_id2 = config_repo.add_directory("/path/to/videos")

    assert dir_id1 > 0
    assert dir_id2 > dir_id1

    directories = config_repo.get_all_directories()
    assert len(directories) == 2

    paths = [d["path"] for d in directories]
    assert "/path/to/photos" in paths
    assert "/path/to/videos" in paths


def test_add_duplicate_directory_raises_error(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Test that adding a duplicate directory path raises an IntegrityError."""
    config_repo.add_directory("/duplicate/path")
    with pytest.raises(sqlite3.IntegrityError):
        config_repo.add_directory("/duplicate/path")


def test_remove_directory(config_repo: SQLiteConfigRepository) -> None:
    """Test removing a directory by ID."""
    dir_id = config_repo.add_directory("/path/to/remove")

    # Verify it was added
    assert len(config_repo.get_all_directories()) == 1

    # Remove it
    config_repo.remove_directory(dir_id)

    # Verify it was removed
    assert len(config_repo.get_all_directories()) == 0


def _legacy_config_db(tmp_path: Path, text_overlay_format: str, *, raw: bool = False) -> Path:
    """Create a v1 config db seeded with a legacy ``text_overlay_format``.

    By default the value is stored JSON-encoded the way
    :meth:`SQLiteConfigRepository.set_app_config` would write it. When
    ``raw`` is true the value is stored as a plain string to emulate a
    picframe 1.x database that was never touched by the 2.0 repository.
    """
    db_path = tmp_path / "config.db3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL
        );
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT INTO schema_version (version) VALUES (1);
        """
    )
    stored = text_overlay_format if raw else json.dumps(text_overlay_format)
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?)",
        ("viewer.text_overlay_format", stored),
    )
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?)",
        ("viewer.show_text_enabled", json.dumps(False)),
    )
    conn.commit()
    conn.close()
    return db_path


def test_v2_migration_rewrites_legacy_strftime_text_overlay_format(
    tmp_path: Path,
) -> None:
    """Legacy strftime values are rewritten to canonical keyword format on open."""
    db_path = _legacy_config_db(tmp_path, "%b %d, %Y")
    repo = SQLiteConfigRepository(str(db_path))
    try:
        migrated = repo.get_app_config("viewer.text_overlay_format")
        assert migrated == "title caption name date folder location"
        version = repo._conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == 2
    finally:
        repo.close()


def test_v2_migration_rewrites_raw_legacy_strftime_value(tmp_path: Path) -> None:
    """Plain (non-JSON) picframe 1.x strftime values are also migrated."""
    db_path = _legacy_config_db(tmp_path, "%b %d, %Y", raw=True)
    repo = SQLiteConfigRepository(str(db_path))
    try:
        assert (
            repo.get_app_config("viewer.text_overlay_format")
            == "title caption name date folder location"
        )
    finally:
        repo.close()


def test_v2_migration_preserves_keyword_text_overlay_format(
    tmp_path: Path,
) -> None:
    """User-selected keyword values are left untouched by the migration."""
    user_value = "title location"
    db_path = _legacy_config_db(tmp_path, user_value)
    repo = SQLiteConfigRepository(str(db_path))
    try:
        assert repo.get_app_config("viewer.text_overlay_format") == user_value
    finally:
        repo.close()


def test_v2_migration_skips_when_key_absent(tmp_path: Path) -> None:
    """Missing ``text_overlay_format`` does not raise during migration."""
    db_path = tmp_path / "config.db3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL
        );
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT INTO schema_version (version) VALUES (1);
        """
    )
    conn.commit()
    conn.close()
    repo = SQLiteConfigRepository(str(db_path))
    try:
        assert repo.get_app_config("viewer.text_overlay_format", "fallback") == ("fallback")
    finally:
        repo.close()
