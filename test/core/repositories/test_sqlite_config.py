"""
Unit tests for the SQLiteConfigRepository.

This module verifies the CRUD operations for application configuration
and directory management using an in-memory SQLite database.
"""

import sqlite3
from collections.abc import Generator

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
    cursor = config_repo._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
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
    assert (
        config_repo.get_app_config("missing_key", "default_val")
        == "default_val"
    )
    assert config_repo.get_app_config("missing_key") is None


def test_update_existing_app_config(
    config_repo: SQLiteConfigRepository,
) -> None:
    """Test updating an existing configuration key."""
    config_repo.set_app_config("key1", "initial")
    config_repo.set_app_config("key1", "updated")
    assert config_repo.get_app_config("key1") == "updated"


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
