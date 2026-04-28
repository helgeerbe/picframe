"""
Unit tests for the SQLiteMediaRepository.

This module verifies the CRUD operations for media metadata management
using an in-memory SQLite database.
"""

import sqlite3
from collections.abc import Generator
from typing import Any

import pytest

from picframe.core.repositories.sqlite_media import SQLiteMediaRepository


@pytest.fixture
def media_repo() -> Generator[SQLiteMediaRepository, None, None]:
    """Provide an in-memory SQLiteMediaRepository for testing."""
    repo = SQLiteMediaRepository(":memory:")
    yield repo
    repo.close()


@pytest.fixture
def sample_media_data() -> dict[str, Any]:
    """Provide sample media data for testing."""
    return {
        "filepath": "/path/to/image.jpg",
        "filename": "image.jpg",
        "directory_id": 1,
        "media_type": "image",
        "file_size": 1024,
        "last_modified": 1678886400.0,
        "width": 1920,
        "height": 1080,
    }


def test_repository_initialization_runs_migrations(
    media_repo: SQLiteMediaRepository,
) -> None:
    """Test that initializing the repository creates the required tables."""
    cursor = media_repo._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = [row["name"] for row in cursor.fetchall()]
    
    assert "media" in tables
    assert "schema_version" in tables


def test_add_and_get_media_item(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test adding and retrieving a media item."""
    media_id = media_repo.add_media_item(sample_media_data)
    assert media_id > 0

    retrieved_item = media_repo.get_media_item(media_id)
    assert retrieved_item is not None
    assert retrieved_item["filepath"] == sample_media_data["filepath"]
    assert retrieved_item["filename"] == sample_media_data["filename"]
    assert retrieved_item["media_type"] == sample_media_data["media_type"]
    assert retrieved_item["is_deleted"] == 0


def test_get_nonexistent_media_item(media_repo: SQLiteMediaRepository) -> None:
    """Test retrieving a non-existent media item returns None."""
    assert media_repo.get_media_item(999) is None


def test_update_media_item(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test updating specific fields of a media item."""
    media_id = media_repo.add_media_item(sample_media_data)
    
    updates = {"width": 800, "height": 600}
    media_repo.update_media_item(media_id, updates)
    
    retrieved_item = media_repo.get_media_item(media_id)
    assert retrieved_item is not None
    assert retrieved_item["width"] == 800
    assert retrieved_item["height"] == 600
    # Ensure other fields remain unchanged
    assert retrieved_item["filepath"] == sample_media_data["filepath"]


def test_delete_media_item(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test soft-deleting a media item."""
    media_id = media_repo.add_media_item(sample_media_data)
    
    media_repo.delete_media_item(media_id)
    
    retrieved_item = media_repo.get_media_item(media_id)
    assert retrieved_item is not None
    assert retrieved_item["is_deleted"] == 1


def test_get_all_media(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test retrieving all active media items."""
    # Add active item
    media_repo.add_media_item(sample_media_data)
    
    # Add deleted item
    deleted_data = sample_media_data.copy()
    deleted_data["filepath"] = "/path/to/deleted.jpg"
    deleted_id = media_repo.add_media_item(deleted_data)
    media_repo.delete_media_item(deleted_id)
    
    # Add another active item
    active_data = sample_media_data.copy()
    active_data["filepath"] = "/path/to/another.jpg"
    media_repo.add_media_item(active_data)
    
    all_media = media_repo.get_all_media()
    
    # Should only return the 2 active items
    assert len(all_media) == 2
    paths = [item["filepath"] for item in all_media]
    assert "/path/to/image.jpg" in paths
    assert "/path/to/another.jpg" in paths
    assert "/path/to/deleted.jpg" not in paths


def test_add_duplicate_filepath_raises_error(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test that adding a duplicate filepath raises an IntegrityError."""
    media_repo.add_media_item(sample_media_data)
    with pytest.raises(sqlite3.IntegrityError):
        media_repo.add_media_item(sample_media_data)
