"""
Unit tests for the SQLiteMediaRepository.

This module verifies the CRUD operations for media metadata management
using an in-memory SQLite database.
"""

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from picframe.core.models.playlist import PlaylistCriteria
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


def _media_record(
    filepath: Path,
    *,
    tags: str = "",
    location: str = "",
    last_modified: float = 100.0,
    exif_datetime: float | None = None,
) -> dict[str, Any]:
    return {
        "filepath": str(filepath),
        "filename": filepath.name,
        "directory_id": 1,
        "media_type": "image",
        "file_size": 100,
        "last_modified": last_modified,
        "exif_datetime": exif_datetime,
        "tags": tags,
        "location": location,
    }


def test_repository_initialization_runs_migrations(
    media_repo: SQLiteMediaRepository,
) -> None:
    """Test that initializing the repository creates the required tables."""
    cursor = media_repo._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    assert "media" in tables
    assert "schema_version" in tables
    columns = [
        row["name"] for row in media_repo._conn.execute("PRAGMA table_info(media)").fetchall()
    ]
    assert "displayed_count" in columns
    assert "last_displayed" in columns
    location_columns = [
        row["name"] for row in media_repo._conn.execute("PRAGMA table_info(locations)").fetchall()
    ]
    queue_columns = [
        row["name"]
        for row in media_repo._conn.execute("PRAGMA table_info(geocoding_queue)").fetchall()
    ]
    index_names = {
        row["name"]
        for row in media_repo._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "language" in location_columns
    assert "language" in queue_columns
    assert "idx_media_active_filepath" in index_names
    assert "idx_media_active_last_modified_filepath" in index_names
    assert "idx_media_active_exif_datetime_filepath" in index_names
    assert "idx_locations_language_rounded_coords" in index_names


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
    """Test marking a media item inactive."""
    media_id = media_repo.add_media_item(sample_media_data)

    media_repo.delete_media_item(media_id)

    retrieved_item = media_repo.get_media_item(media_id)
    assert retrieved_item is not None
    assert retrieved_item["is_deleted"] == 1


def test_remove_media_item_deletes_cache_row(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    media_id = media_repo.add_media_item(sample_media_data)

    media_repo.remove_media_item(media_id)

    assert media_repo.get_media_item(media_id) is None


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


def test_add_duplicate_filepath_updates_existing(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    """Test that adding a duplicate filepath updates the existing record."""
    media_repo.add_media_item(sample_media_data)

    # Modify data and add again
    updated_data = sample_media_data.copy()
    updated_data["file_size"] = 2048
    media_repo.add_media_item(updated_data)

    # Verify it was updated, not duplicated
    all_media = media_repo.get_all_media()
    assert len(all_media) == 1
    assert all_media[0]["file_size"] == 2048


def test_record_media_displayed_preserves_stats_on_reindex(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    media_id = media_repo.add_media_item(sample_media_data)

    updated_item = media_repo.record_media_displayed(media_id)

    assert updated_item is not None
    assert updated_item["displayed_count"] == 1
    assert updated_item["last_displayed"] > 0

    reindexed_data = sample_media_data.copy()
    reindexed_data["file_size"] = 4096
    reindexed_data["displayed_count"] = 0
    reindexed_data["last_displayed"] = 0.0
    same_id = media_repo.add_media_item(reindexed_data)
    reindexed_item = media_repo.get_media_item(same_id)

    assert same_id == media_id
    assert reindexed_item is not None
    assert reindexed_item["displayed_count"] == 1
    assert reindexed_item["last_displayed"] == updated_item["last_displayed"]


def test_query_media_applies_playlist_filters_and_sorting(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    holiday = root / "holiday"
    family = root / "family"
    holiday.mkdir(parents=True)
    family.mkdir()

    media_repo.add_media_item(
        {
            "filepath": str(holiday / "beach.jpg"),
            "filename": "beach.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 100.0,
            "exif_datetime": 1_700_000_000.0,
            "tags": "family, beach",
            "location": "Barcelona",
            "rating": 3,
        }
    )
    media_repo.add_media_item(
        {
            "filepath": str(holiday / "city.jpg"),
            "filename": "city.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 200.0,
            "exif_datetime": 1_710_000_000.0,
            "tags": "city",
            "location": "Berlin",
            "rating": 5,
        }
    )
    media_repo.add_media_item(
        {
            "filepath": str(family / "portrait.jpg"),
            "filename": "portrait.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 300.0,
            "exif_datetime": 1_700_000_000.0,
            "tags": "family",
            "location": "Barcelona",
            "rating": 4,
        }
    )

    criteria = PlaylistCriteria(
        pic_dir=str(root),
        subdirectory="holiday",
        date_from="2023-11-01",
        date_to="2024-03-01",
        location_filter="Barcelona",
        tags_filter="family AND beach",
        shuffle=False,
        sort_cols="rating DESC",
        recent_n=0,
    )

    result = media_repo.query_media(criteria)

    assert [item["filename"] for item in result] == ["beach.jpg"]


def test_query_media_path_range_filter_matches_prefix_scope(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    holiday = root / "holiday"
    sibling = tmp_path / "Pictures2"
    holiday.mkdir(parents=True)
    sibling.mkdir()
    media_repo.add_media_item(_media_record(root / "root.jpg"))
    media_repo.add_media_item(_media_record(holiday / "beach.jpg"))
    media_repo.add_media_item(_media_record(sibling / "outside.jpg"))

    root_result = media_repo.query_media(
        PlaylistCriteria(pic_dir=str(root), shuffle=False, sort_cols="fname ASC")
    )
    holiday_result = media_repo.query_media(
        PlaylistCriteria(
            pic_dir=str(root),
            subdirectory="holiday",
            shuffle=False,
            sort_cols="fname ASC",
        )
    )

    assert [item["filename"] for item in root_result] == ["beach.jpg", "root.jpg"]
    assert [item["filename"] for item in holiday_result] == ["beach.jpg"]


def test_order_clause_avoids_sql_random_for_standard_shuffle() -> None:
    standard_clause = SQLiteMediaRepository._build_order_clause(
        PlaylistCriteria(shuffle=True, shuffle_mode="standard")
    )
    fewer_repeats_clause = SQLiteMediaRepository._build_order_clause(
        PlaylistCriteria(shuffle=True, shuffle_mode="fewer_repeats")
    )
    invalid_clause = SQLiteMediaRepository._build_order_clause(
        PlaylistCriteria(shuffle=True, shuffle_mode="unknown")
    )
    sorted_clause = SQLiteMediaRepository._build_order_clause(
        PlaylistCriteria(
            shuffle=False,
            shuffle_mode="fewer_repeats",
            sort_cols="rating DESC",
        )
    )

    assert "RANDOM()" not in standard_clause
    assert "m.filepath ASC" in standard_clause
    assert "RANDOM()" not in fewer_repeats_clause
    assert "m.filepath ASC" in fewer_repeats_clause
    assert "RANDOM()" not in invalid_clause
    assert "m.filepath ASC" in invalid_clause
    assert "RANDOM()" not in sorted_clause
    assert sorted_clause.startswith("m.rating DESC")


def test_query_media_uses_legacy_boolean_filter_phrases(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "phrase.jpg", tags="family beach"))
    media_repo.add_media_item(_media_record(root / "separate.jpg", tags="family, beach"))
    media_repo.add_media_item(_media_record(root / "family.jpg", tags="family"))
    media_repo.add_media_item(_media_record(root / "city.jpg", tags="city"))
    media_repo.add_media_item(_media_record(root / "friends-holiday.jpg", tags="friends, holiday"))

    def names_for(tags_filter: str) -> set[str]:
        result = media_repo.query_media(
            PlaylistCriteria(
                pic_dir=str(root),
                tags_filter=tags_filter,
                shuffle=False,
                sort_cols="fname ASC",
            )
        )
        return {item["filename"] for item in result}

    assert names_for("family beach") == {"phrase.jpg"}
    assert names_for("family AND beach") == {"phrase.jpg", "separate.jpg"}
    assert names_for("city OR beach") == {"city.jpg", "phrase.jpg", "separate.jpg"}
    assert names_for("family AND NOT beach") == {"family.jpg"}
    assert names_for("(family OR friends) AND holiday") == {"friends-holiday.jpg"}


def test_query_media_location_filter_matches_unquoted_and_quoted_phrases(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "new-york.jpg", location="New York City"))
    media_repo.add_media_item(_media_record(root / "york-new.jpg", location="York New"))

    for expression in ("New York", '"New York"'):
        result = media_repo.query_media(
            PlaylistCriteria(
                pic_dir=str(root),
                location_filter=expression,
                shuffle=False,
            )
        )
        assert {item["filename"] for item in result} == {"new-york.jpg"}


def test_query_media_escapes_like_wildcards_in_filters(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "percent.jpg", tags="100% real"))
    media_repo.add_media_item(_media_record(root / "plain.jpg", tags="100x real"))
    media_repo.add_media_item(_media_record(root / "underscore.jpg", tags="a_b"))
    media_repo.add_media_item(_media_record(root / "letters.jpg", tags="axb"))
    media_repo.add_media_item(_media_record(root / "slash.jpg", tags=r"path\tag"))

    def names_for(tags_filter: str) -> set[str]:
        result = media_repo.query_media(
            PlaylistCriteria(pic_dir=str(root), tags_filter=tags_filter, shuffle=False)
        )
        return {item["filename"] for item in result}

    assert names_for("%") == {"percent.jpg"}
    assert names_for("_") == {"underscore.jpg"}
    assert names_for("\\") == {"slash.jpg"}


def test_count_media_uses_selected_folder_scope_and_selection_filters(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    holiday = root / "holiday"
    family = root / "family"
    holiday.mkdir(parents=True)
    family.mkdir()
    media_repo.add_media_item(
        _media_record(
            holiday / "beach.jpg",
            tags="family, beach",
            location="Barcelona",
            exif_datetime=1_700_000_000.0,
        )
    )
    media_repo.add_media_item(
        _media_record(
            holiday / "city.jpg",
            tags="city",
            location="Berlin",
            exif_datetime=1_710_000_000.0,
        )
    )
    media_repo.add_media_item(
        _media_record(
            holiday / "old.jpg",
            tags="family, beach",
            location="Barcelona",
            exif_datetime=1_600_000_000.0,
        )
    )
    media_repo.add_media_item(_media_record(family / "portrait.jpg", tags="family"))
    media_repo.add_media_item(_media_record(tmp_path / "outside.jpg", tags="family"))

    counts = media_repo.count_media(
        PlaylistCriteria(
            pic_dir=str(root),
            subdirectory="holiday",
            date_from="2023-11-01",
            date_to="2024-03-01",
            location_filter="Barcelona",
            tags_filter="family AND beach",
        )
    )

    assert counts == {
        "selected_count": 1,
        "total_count": 3,
        "scope": "subdirectory",
        "scope_label": "holiday",
    }

    all_counts = media_repo.count_media(PlaylistCriteria(pic_dir=str(root), tags_filter="family"))

    assert all_counts["selected_count"] == 3
    assert all_counts["total_count"] == 4
    assert all_counts["scope"] == "pic_dir"
    assert all_counts["scope_label"] == str(root)


def test_query_media_ignores_invalid_filters_and_sort_columns(
    media_repo: SQLiteMediaRepository, sample_media_data: dict[str, Any]
) -> None:
    media_repo.add_media_item(sample_media_data | {"tags": "family"})

    criteria = PlaylistCriteria(
        pic_dir="/path",
        tags_filter="family AND OR",
        shuffle=False,
        sort_cols="unknown DESC, fname ASC",
    )

    result = media_repo.query_media(criteria)

    assert [item["filename"] for item in result] == ["image.jpg"]


def test_get_filter_options_returns_distinct_values(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    (root / "holiday").mkdir(parents=True)
    media_repo.add_media_item(
        {
            "filepath": str(root / "holiday" / "beach.jpg"),
            "filename": "beach.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 100.0,
            "tags": "family, beach",
            "location": "Barcelona",
        }
    )

    options = media_repo.get_filter_options(str(root))

    assert options["subdirectories"] == ["holiday"]
    assert options["locations"] == []
    assert options["tags"] == ["beach", "family"]
    assert {"key": "fname", "label": "File name"} in options["sort_columns"]


def test_search_location_options_returns_capped_counts(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "berlin-1.jpg", location="Berlin"))
    media_repo.add_media_item(_media_record(root / "berlin-2.jpg", location="Berlin"))
    media_repo.add_media_item(_media_record(root / "bern.jpg", location="Bern"))
    media_repo.add_media_item(_media_record(root / "barcelona.jpg", location="Barcelona"))
    deleted_id = media_repo.add_media_item(_media_record(root / "deleted.jpg", location="Berlin"))
    media_repo.delete_media_item(deleted_id)

    assert media_repo.search_location_options("ber", limit=1) == [{"value": "Berlin", "count": 2}]
    assert media_repo.search_location_options("ber", limit=10) == [
        {"value": "Berlin", "count": 2},
        {"value": "Bern", "count": 1},
    ]


def test_search_location_options_escapes_like_wildcards(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "percent.jpg", location="100% City"))
    media_repo.add_media_item(_media_record(root / "plain.jpg", location="100x City"))

    assert media_repo.search_location_options("%", limit=10) == [{"value": "100% City", "count": 1}]


def test_location_cache_is_language_aware(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(
        _media_record(root / "gps.jpg", location="", last_modified=100.0)
        | {"latitude": 52.5, "longitude": 13.4}
    )
    media_repo.save_location(52.5, 13.4, "Berlin, Germany", language="en")
    media_repo.save_location(52.5, 13.4, "Berlin, Deutschland", language="de")

    assert media_repo.get_location(52.5, 13.4, language="en") == "Berlin, Germany"
    assert media_repo.get_location(52.5, 13.4, language="de") == "Berlin, Deutschland"
    assert media_repo.get_location(52.5, 13.4, language="fr") is None

    english = media_repo.query_media(
        PlaylistCriteria(pic_dir=str(root), shuffle=False, location_language="en")
    )
    german = media_repo.query_media(
        PlaylistCriteria(pic_dir=str(root), shuffle=False, location_language="de")
    )

    assert english[0]["location"] == "Berlin, Germany"
    assert german[0]["location"] == "Berlin, Deutschland"


def test_location_join_uses_rounded_coordinate_expression_index(
    media_repo: SQLiteMediaRepository,
) -> None:
    location_join, location_params = SQLiteMediaRepository._location_join_sql("de")
    with media_repo._lock:
        plan_rows = media_repo._conn.execute(
            f"""
            EXPLAIN QUERY PLAN
            SELECT m.id
            FROM media m
            {location_join}
            WHERE m.is_deleted = 0
            """,
            location_params,
        ).fetchall()

    plan = "\n".join(str(row["detail"]) for row in plan_rows)
    assert "idx_locations_language_rounded_coords" in plan


def test_location_lookup_waits_for_repository_connection_lock(
    media_repo: SQLiteMediaRepository,
) -> None:
    media_repo.save_location(52.5, 13.4, "Berlin, Germany", language="en")
    started = threading.Event()
    completed = threading.Event()
    result: list[str | None] = []

    def lookup_location() -> None:
        started.set()
        result.append(media_repo.get_location(52.5, 13.4, language="en"))
        completed.set()

    with media_repo._lock:
        thread = threading.Thread(target=lookup_location)
        thread.start()
        assert started.wait(timeout=1.0)
        assert not completed.wait(timeout=0.05)

    assert completed.wait(timeout=1.0)
    thread.join(timeout=1.0)
    assert result == ["Berlin, Germany"]


def test_count_media_skips_location_join_without_location_filter(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "family.jpg", tags="family"))
    statements: list[str] = []
    media_repo._conn.set_trace_callback(statements.append)
    try:
        counts = media_repo.count_media(PlaylistCriteria(pic_dir=str(root), tags_filter="family"))
    finally:
        media_repo._conn.set_trace_callback(None)

    count_selects = [
        statement.upper() for statement in statements if "SELECT COUNT" in statement.upper()
    ]
    assert counts["selected_count"] == 1
    assert counts["total_count"] == 1
    assert len(count_selects) == 2
    assert all("JOIN LOCATIONS" not in statement for statement in count_selects)


def test_count_media_joins_location_only_for_location_filter(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(_media_record(root / "berlin.jpg", location="Berlin"))
    statements: list[str] = []
    media_repo._conn.set_trace_callback(statements.append)
    try:
        counts = media_repo.count_media(
            PlaylistCriteria(pic_dir=str(root), location_filter="Berlin")
        )
    finally:
        media_repo._conn.set_trace_callback(None)

    count_selects = [
        statement.upper() for statement in statements if "SELECT COUNT" in statement.upper()
    ]
    assert counts["selected_count"] == 1
    assert counts["total_count"] == 1
    assert len(count_selects) == 2
    assert sum("JOIN LOCATIONS" in statement for statement in count_selects) == 1


def test_location_search_and_counts_use_requested_language(
    media_repo: SQLiteMediaRepository, tmp_path: Path
) -> None:
    root = tmp_path / "Pictures"
    root.mkdir()
    media_repo.add_media_item(
        _media_record(root / "gps.jpg", location="", last_modified=100.0)
        | {"latitude": 52.5, "longitude": 13.4}
    )
    media_repo.save_location(52.5, 13.4, "Berlin, Germany", language="en")
    media_repo.save_location(52.5, 13.4, "Berlin, Deutschland", language="de")

    assert media_repo.search_location_options(
        "deutsch",
        limit=10,
        location_language="de",
    ) == [{"value": "Berlin, Deutschland", "count": 1}]
    assert (
        media_repo.search_location_options(
            "deutsch",
            limit=10,
            location_language="en",
        )
        == []
    )
    assert (
        media_repo.count_media(
            PlaylistCriteria(
                pic_dir=str(root),
                location_filter="Deutschland",
                location_language="de",
            )
        )["selected_count"]
        == 1
    )
    assert (
        media_repo.count_media(
            PlaylistCriteria(
                pic_dir=str(root),
                location_filter="Deutschland",
                location_language="en",
            )
        )["selected_count"]
        == 0
    )


def test_geocoding_queue_is_language_aware(media_repo: SQLiteMediaRepository) -> None:
    media_repo.enqueue_location_lookup(52.5, 13.4, language="en")
    media_repo.enqueue_location_lookup(52.5, 13.4, language="de")
    media_repo.enqueue_location_lookup(52.5, 13.4, language="de")

    assert media_repo.dequeue_location_lookup() == (52.5, 13.4, "en")
    assert media_repo.dequeue_location_lookup() == (52.5, 13.4, "de")
    assert media_repo.dequeue_location_lookup() is None


def test_get_active_directory_ids_returns_only_active(media_repo: SQLiteMediaRepository) -> None:
    """Only directory IDs referenced by non-deleted media are returned."""
    media_repo.add_media_item(
        {
            "filepath": "/pics/active.jpg",
            "filename": "active.jpg",
            "directory_id": 10,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 1.0,
        }
    )
    media_repo.add_media_item(
        {
            "filepath": "/pics/deleted.jpg",
            "filename": "deleted.jpg",
            "directory_id": 20,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 1.0,
        }
    )
    media_repo.delete_media_by_path("/pics/deleted.jpg")

    active_ids = media_repo.get_active_directory_ids()

    assert active_ids == {10}


def test_get_active_directory_ids_empty(media_repo: SQLiteMediaRepository) -> None:
    """An empty media cache returns an empty set."""
    assert media_repo.get_active_directory_ids() == set()


def test_get_active_directory_ids_includes_dir_with_mixed_active_and_deleted(
    media_repo: SQLiteMediaRepository,
) -> None:
    """A directory with at least one active media item is returned even if others are deleted."""
    # Active item in directory 10
    media_repo.add_media_item(
        {
            "filepath": "/pics/mixed_active.jpg",
            "filename": "mixed_active.jpg",
            "directory_id": 10,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 1.0,
        }
    )
    # Soft-deleted item in the same directory 10
    deleted_id = media_repo.add_media_item(
        {
            "filepath": "/pics/mixed_deleted.jpg",
            "filename": "mixed_deleted.jpg",
            "directory_id": 10,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 2.0,
        }
    )
    media_repo.delete_media_item(deleted_id)

    # Directory 20 is fully soft-deleted and should not be returned
    fully_deleted_id = media_repo.add_media_item(
        {
            "filepath": "/pics/fully_deleted.jpg",
            "filename": "fully_deleted.jpg",
            "directory_id": 20,
            "media_type": "image",
            "file_size": 100,
            "last_modified": 1.0,
        }
    )
    media_repo.delete_media_item(fully_deleted_id)

    active_ids = media_repo.get_active_directory_ids()

    assert 10 in active_ids
    assert 20 not in active_ids
