from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from picframe.core.models.media import DisplayItem, DisplayLayout, MediaType
from picframe.core.models.playlist import (
    SHUFFLE_MODE_AGE_WEIGHTED,
    SHUFFLE_MODE_FEWER_REPEATS,
    SHUFFLE_MODE_STANDARD,
    PlaylistCriteria,
)
from picframe.core.repositories.interfaces import IMediaRepository
from picframe.core.services.playlist import PlaylistManager


def _stat_for_rows(rows: list[dict[str, Any]]) -> Mock:
    rows_by_path = {str(row["filepath"]): row for row in rows}

    def stat_side_effect(filepath: str, **kwargs: Any) -> SimpleNamespace:
        # Python 3.11+ pathlib.Path.resolve() calls os.stat(path, follow_symlinks=True).
        # Paths outside the media table (e.g. ~/.picframe) fall back to a default stat.
        row = rows_by_path.get(str(filepath))
        if row is None:
            return SimpleNamespace(st_size=0, st_mtime=0.0)
        return SimpleNamespace(
            st_size=row.get("file_size", 0),
            st_mtime=row.get("last_modified", 0.0),
        )

    return Mock(side_effect=stat_side_effect)


@pytest.fixture
def mock_media_repo() -> Mock:
    repo = Mock(spec=IMediaRepository)
    repo.get_all_media.return_value = [
        {
            "id": 1,
            "filepath": "/path/to/image1.jpg",
            "filename": "image1.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1234567890.0,
            "width": 1920,
            "height": 1080,
            "orientation": 1,
            "is_deleted": 0,
        },
        {
            "id": 2,
            "filepath": "/path/to/image2.jpg",
            "filename": "image2.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 2048,
            "last_modified": 1234567891.0,
            "width": 800,
            "height": 600,
            "orientation": 1,
            "is_deleted": 0,
        },
        {
            "id": 3,
            "filepath": "/path/to/video1.mp4",
            "filename": "video1.mp4",
            "directory_id": 1,
            "media_type": "video",
            "file_size": 4096,
            "last_modified": 1234567892.0,
            "duration": 10.5,
            "is_deleted": 0,
        },
    ]
    repo.record_media_displayed.side_effect = lambda media_id, **_: next(
        (item for item in repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    repo.get_media_item.side_effect = lambda media_id, **_: next(
        (item for item in repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    return repo


def test_build_playlist_no_shuffle(mock_media_repo: Mock) -> None:
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)

    assert len(manager._playlist) == 3
    assert len(manager._display_playlist) == 3
    assert manager._current_index == 0
    assert manager._playlist[0]["id"] == 1
    assert manager._playlist[1]["id"] == 2
    assert manager._playlist[2]["id"] == 3


def test_build_playlist_empty(mock_media_repo: Mock) -> None:
    mock_media_repo.get_all_media.return_value = []
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist()

    assert len(manager._playlist) == 0
    assert manager._current_index == -1


@patch("os.path.isfile", return_value=True)
def test_get_next(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        manager = PlaylistManager(mock_media_repo)
        manager.build_playlist(shuffle=False)

        item1 = manager.get_next()
        assert isinstance(item1, DisplayItem)
        assert item1.layout == DisplayLayout.SINGLE
        assert item1.id == 1
        assert item1.media_type == MediaType.IMAGE
        mock_media_repo.record_media_displayed.assert_called_once_with(
            1,
            location_language="en",
        )

        item2 = manager.get_next()
        assert item2 is not None
        assert item2.id == 2

        item3 = manager.get_next()
        assert item3 is not None
        assert item3.id == 3
        assert item3.media_type == MediaType.VIDEO

        # Should rebuild and return first item again
        item4 = manager.get_next()
        assert item4 is not None
        assert item4.id == 1


@patch("os.path.isfile", return_value=True)
def test_get_previous(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        manager = PlaylistManager(mock_media_repo)
        manager.build_playlist(shuffle=False)

        # No history yet
        assert manager.get_previous() is None

        manager.get_next()  # id 1
        # Only 1 item in history, no previous
        assert manager.get_previous() is None

        manager.get_next()  # id 2
        manager.get_next()  # id 3

        # Now we have history: [1, 2, 3]
        # Current item is 3, previous should be 2
        prev_item = manager.get_previous()
        assert prev_item is not None
        assert prev_item.id == 2

        # History is now [1, 2]
        # Current item is 2, previous should be 1
        prev_item2 = manager.get_previous()
        assert prev_item2 is not None
        assert prev_item2.id == 1

        # History is now [1]
        # Current item is 1, no previous
        assert manager.get_previous() is None


@patch("os.path.isfile", return_value=True)
def test_get_next_after_previous(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        manager = PlaylistManager(mock_media_repo)
        manager.build_playlist(shuffle=False)

        manager.get_next()  # id 1
        manager.get_next()  # id 2
        manager.get_next()  # id 3

        manager.get_previous()  # returns 2

        # Next should be 3 again
        next_item = manager.get_next()
        assert next_item is not None
        assert next_item.id == 3


def test_build_playlist_uses_configured_criteria(mock_media_repo: Mock) -> None:
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.pic_dir": "/pictures",
        "model.subdirectory": "holiday",
        "model.date_from": "2024-01-01",
        "model.date_to": "2024-01-31",
        "model.location_filter": "Berlin",
        "model.tags_filter": "family",
        "model.sort_cols": "rating DESC",
        "model.recent_n": 14,
        "model.reshuffle_num": 3,
    }.get(key, default)
    config_repo.get_app_config_bool.return_value = False
    mock_media_repo.query_media.return_value = mock_media_repo.get_all_media.return_value

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    criteria = mock_media_repo.query_media.call_args[0][0]
    assert isinstance(criteria, PlaylistCriteria)
    assert criteria.pic_dir == "/pictures"
    assert criteria.subdirectory == "holiday"
    assert criteria.date_from == "2024-01-01"
    assert criteria.date_to == "2024-01-31"
    assert criteria.location_filter == "Berlin"
    assert criteria.tags_filter == "family"
    assert criteria.shuffle is False
    assert criteria.shuffle_mode == SHUFFLE_MODE_STANDARD
    assert criteria.sort_cols == "rating DESC"
    assert criteria.recent_n == 14
    assert manager._reshuffle_num == 3


def test_invalid_shuffle_mode_falls_back_to_standard(mock_media_repo: Mock) -> None:
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.shuffle_mode": "chaos",
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.shuffle": True,
        "model.portrait_pairs": False,
    }.get(key, default)
    mock_media_repo.query_media.return_value = mock_media_repo.get_all_media.return_value

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    criteria = mock_media_repo.query_media.call_args[0][0]
    assert criteria.shuffle_mode == SHUFFLE_MODE_STANDARD
    assert manager._shuffle_mode == SHUFFLE_MODE_STANDARD


def test_standard_shuffle_keeps_recent_media_before_older_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 2_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {"id": "old-1", "last_modified": now - (10 * 24 * 60 * 60)},
        {"id": "recent-1", "last_modified": now - (2 * 24 * 60 * 60)},
        {"id": "old-2", "last_modified": now - (8 * 24 * 60 * 60)},
        {"id": "recent-2", "last_modified": now - (1 * 24 * 60 * 60)},
    ]

    shuffled = PlaylistManager._shuffle_standard_rows(rows, recent_n=7)

    assert {row["id"] for row in shuffled[:2]} == {"recent-1", "recent-2"}
    assert {row["id"] for row in shuffled[2:]} == {"old-1", "old-2"}


def test_fewer_repeats_pushes_recently_displayed_slots_later(
    mock_media_repo: Mock,
) -> None:
    rows = [
        {
            "id": 1,
            "filepath": "/path/to/old.jpg",
            "filename": "old.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 100.0,
            "is_deleted": 0,
        },
        {
            "id": 2,
            "filepath": "/path/to/middle.jpg",
            "filename": "middle.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 200.0,
            "is_deleted": 0,
        },
        {
            "id": 3,
            "filepath": "/path/to/recent.jpg",
            "filename": "recent.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 900.0,
            "is_deleted": 0,
        },
    ]
    mock_media_repo.query_media.return_value = rows
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.shuffle_mode": SHUFFLE_MODE_FEWER_REPEATS,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.shuffle": True,
        "model.portrait_pairs": False,
    }.get(key, default)
    candidate_orders = [
        [rows[2], rows[1], rows[0]],
        [rows[0], rows[1], rows[2]],
        [rows[1], rows[2], rows[0]],
    ]

    def fake_shuffle(candidate: list[list[dict[str, Any]]]) -> None:
        order = candidate_orders.pop(0) if candidate_orders else [rows[2], rows[0], rows[1]]
        candidate[:] = [[item] for item in order]

    manager = PlaylistManager(mock_media_repo, config_repo)
    with patch("random.shuffle", fake_shuffle):
        manager.build_playlist()

    assert [slot[0]["id"] for slot in manager._display_playlist] == [1, 2, 3]


def test_fewer_repeats_preserves_portrait_pair_slots(mock_media_repo: Mock) -> None:
    rows = [
        {
            "id": 1,
            "filepath": "/path/to/portrait1.jpg",
            "filename": "portrait1.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 900.0,
            "is_portrait": 1,
        },
        {
            "id": 2,
            "filepath": "/path/to/portrait2.jpg",
            "filename": "portrait2.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 100.0,
            "is_portrait": 1,
        },
        {
            "id": 3,
            "filepath": "/path/to/portrait3.jpg",
            "filename": "portrait3.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 200.0,
            "is_portrait": 1,
        },
        {
            "id": 4,
            "filepath": "/path/to/portrait4.jpg",
            "filename": "portrait4.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "last_displayed": 300.0,
            "is_portrait": 1,
        },
    ]
    mock_media_repo.query_media.return_value = rows
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.shuffle_mode": SHUFFLE_MODE_FEWER_REPEATS,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.shuffle": True,
        "model.portrait_pairs": True,
    }.get(key, default)

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    pair_ids = {tuple(item["id"] for item in slot) for slot in manager._display_playlist}
    assert pair_ids == {(1, 2), (3, 4)}


@patch("os.path.isfile", return_value=True)
def test_portrait_pairs_pair_only_images_and_exclude_videos(
    mock_isfile: Mock,
    mock_media_repo: Mock,
) -> None:
    mock_media_repo.get_all_media.return_value = [
        {
            "id": 1,
            "filepath": "/path/to/portrait1.jpg",
            "filename": "portrait1.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
        {
            "id": 2,
            "filepath": "/path/to/video.mp4",
            "filename": "video.mp4",
            "directory_id": 1,
            "media_type": "video",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
        {
            "id": 3,
            "filepath": "/path/to/portrait2.jpg",
            "filename": "portrait2.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
        {
            "id": 4,
            "filepath": "/path/to/landscape.jpg",
            "filename": "landscape.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 0,
        },
        {
            "id": 5,
            "filepath": "/path/to/portrait3.jpg",
            "filename": "portrait3.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
    ]
    mock_media_repo.record_media_displayed.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    mock_media_repo.get_media_item.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.reshuffle_num": 1,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.portrait_pairs": True,
        "model.shuffle": False,
    }.get(key, default)
    mock_media_repo.query_media.return_value = mock_media_repo.get_all_media.return_value

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        first = manager.get_next()
        assert first is not None
        assert first.layout == DisplayLayout.PORTRAIT_PAIR
        assert [item.id for item in first.items] == [1, 3]

        second = manager.get_next()
        assert second is not None
        assert second.layout == DisplayLayout.SINGLE
        assert second.id == 2
        assert second.media_type == MediaType.VIDEO

        third = manager.get_next()
        assert third is not None
        assert third.layout == DisplayLayout.SINGLE
        assert third.id == 4

        fourth = manager.get_next()
        assert fourth is not None
        assert fourth.layout == DisplayLayout.SINGLE
        assert fourth.id == 5

    assert mock_media_repo.record_media_displayed.call_args_list[0].args == (1,)
    assert mock_media_repo.record_media_displayed.call_args_list[1].args == (3,)


@patch("os.path.isfile", return_value=True)
def test_delete_current_pair_validates_target_ids(
    mock_isfile: Mock,
    mock_media_repo: Mock,
) -> None:
    mock_media_repo.get_all_media.return_value = [
        {
            "id": 1,
            "filepath": "/path/to/portrait1.jpg",
            "filename": "portrait1.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
        {
            "id": 2,
            "filepath": "/path/to/portrait2.jpg",
            "filename": "portrait2.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
    ]
    mock_media_repo.record_media_displayed.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    mock_media_repo.get_media_item.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.reshuffle_num": 1,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.portrait_pairs": True,
        "model.shuffle": False,
    }.get(key, default)
    mock_media_repo.query_media.return_value = mock_media_repo.get_all_media.return_value

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()
    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        manager.get_next()

    assert manager.resolve_current_delete_ids("left", [1]) == [1]
    assert manager.resolve_current_delete_ids("right", [2]) == [2]
    assert manager.resolve_current_delete_ids("both", [1, 2]) == [1, 2]
    assert manager.resolve_current_delete_ids("right", [1]) == []


@patch("os.path.isfile", return_value=False)
def test_get_next_marks_missing_file_inactive_and_does_not_count(
    mock_isfile: Mock,
    mock_media_repo: Mock,
) -> None:
    mock_media_repo.get_all_media.return_value = [mock_media_repo.get_all_media.return_value[0]]
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)

    item = manager.get_next()

    assert item is not None
    assert item.id == 0
    mock_media_repo.delete_media_item.assert_called_once_with(1)
    mock_media_repo.record_media_displayed.assert_not_called()


@patch("os.path.isfile", return_value=True)
def test_get_next_skips_changed_file_and_requests_reindex(
    mock_isfile: Mock,
    mock_media_repo: Mock,
) -> None:
    mock_media_repo.get_all_media.return_value = [mock_media_repo.get_all_media.return_value[0]]
    publisher = Mock()
    manager = PlaylistManager(mock_media_repo, event_publisher=publisher)
    manager.build_playlist(shuffle=False)

    changed_stat = Mock()
    changed_stat.st_size = 9999
    changed_stat.st_mtime = 1234567890.0

    with patch("os.stat", return_value=changed_stat):
        item = manager.get_next()

    assert item is not None
    assert item.id == 0
    mock_media_repo.delete_media_item.assert_not_called()
    mock_media_repo.record_media_displayed.assert_not_called()
    event = publisher.publish.call_args.args[0]
    assert event.event_type == "modified"
    assert event.path == "/path/to/image1.jpg"


@patch("os.path.isfile", return_value=True)
def test_portrait_pair_with_missing_side_displays_remaining_image(
    mock_isfile: Mock,
    mock_media_repo: Mock,
) -> None:
    mock_media_repo.get_all_media.return_value = [
        {
            "id": 1,
            "filepath": "/path/to/portrait1.jpg",
            "filename": "portrait1.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
        {
            "id": 2,
            "filepath": "/path/to/portrait2.jpg",
            "filename": "portrait2.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": 1.0,
            "is_portrait": 1,
        },
    ]
    mock_media_repo.query_media.return_value = mock_media_repo.get_all_media.return_value
    mock_media_repo.get_media_item.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    mock_media_repo.record_media_displayed.side_effect = lambda media_id, **_: next(
        (item for item in mock_media_repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.reshuffle_num": 1,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.portrait_pairs": True,
        "model.shuffle": False,
    }.get(key, default)

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    mock_isfile.side_effect = lambda path: path == "/path/to/portrait1.jpg"
    with patch("os.stat", _stat_for_rows(mock_media_repo.get_all_media.return_value)):
        item = manager.get_next()

    assert item is not None
    assert item.layout == DisplayLayout.SINGLE
    assert item.id == 1
    mock_media_repo.delete_media_item.assert_called_once_with(2)
    mock_media_repo.record_media_displayed.assert_called_once_with(
        1,
        location_language="en",
    )


def test_purge_orphaned_directories_returns_zero_without_config_repo(
    mock_media_repo: Mock,
) -> None:
    """When no config repository is configured, purge returns 0 and does not query media."""
    manager = PlaylistManager(mock_media_repo, config_repository=None)
    mock_media_repo.get_active_directory_ids.reset_mock()

    result = manager.purge_orphaned_directories()

    assert result == 0
    mock_media_repo.get_active_directory_ids.assert_not_called()


def test_purge_orphaned_directories_invokes_config_repo_with_active_ids(
    mock_media_repo: Mock,
) -> None:
    """When both repos are present, active IDs are fetched and passed to config repo."""
    config_repo = Mock()
    active_ids = {1, 2, 3}
    mock_media_repo.get_active_directory_ids.return_value = active_ids
    config_repo.purge_orphaned_directories.return_value = 42

    manager = PlaylistManager(mock_media_repo, config_repository=config_repo)
    result = manager.purge_orphaned_directories()

    mock_media_repo.get_active_directory_ids.assert_called_once_with()
    config_repo.purge_orphaned_directories.assert_called_once_with(active_ids)
    assert result == 42


# ---------------------------------------------------------------------------
# Age-weighted shuffle mode (ticket #723)
# ---------------------------------------------------------------------------

_DAY_SECONDS = 24 * 60 * 60


def test_age_weighted_places_newer_media_before_older_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Newer files should appear earlier on average than older files."""
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {"id": "old", "last_modified": now - (10 * 365 * _DAY_SECONDS)},
        {"id": "new", "last_modified": now - (1 * _DAY_SECONDS)},
    ]

    first_is_new = 0
    trials = 200
    for _ in range(trials):
        shuffled = PlaylistManager._shuffle_age_weighted(rows, recency_half_life_days=365.0)
        if shuffled[0]["id"] == "new":
            first_is_new += 1

    # With a 10-year age gap and a 1-year half-life the bias is very strong.
    assert first_is_new > int(trials * 0.9)


def test_age_weighted_preserves_all_rows_without_sample_limit() -> None:
    rows = [{"id": i, "last_modified": float(i)} for i in range(5)]
    shuffled = PlaylistManager._shuffle_age_weighted(rows, recency_half_life_days=365.0)
    assert {row["id"] for row in shuffled} == {0, 1, 2, 3, 4}
    assert len(shuffled) == 5


def test_age_weighted_sample_limit_truncates_to_subset() -> None:
    rows = [{"id": i, "last_modified": float(i)} for i in range(10)]
    shuffled = PlaylistManager._shuffle_age_weighted(
        rows, recency_half_life_days=365.0, sample_limit=3
    )
    assert len(shuffled) == 3
    assert {row["id"] for row in shuffled}.issubset(set(range(10)))


def test_age_weighted_sample_limit_zero_or_negative_means_unlimited() -> None:
    rows = [{"id": i, "last_modified": float(i)} for i in range(4)]
    assert len(PlaylistManager._shuffle_age_weighted(rows, 365.0, sample_limit=0)) == 4
    assert len(PlaylistManager._shuffle_age_weighted(rows, 365.0, sample_limit=-5)) == 4


def test_age_weighted_handles_empty_and_single_rows() -> None:
    assert PlaylistManager._shuffle_age_weighted([], 365.0) == []
    single = [{"id": 1, "last_modified": 1.0}]
    assert PlaylistManager._shuffle_age_weighted(single, 365.0) == single


def test_age_weighted_prefers_exif_datetime_over_last_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """exif_datetime (capture time) should drive age, not last_modified."""
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        # Old capture time, recent mtime -> should be treated as OLD.
        {"id": "old-capture", "exif_datetime": now - (2000 * _DAY_SECONDS), "last_modified": now},
        # Recent capture time, old mtime -> should be treated as NEW.
        {"id": "new-capture", "exif_datetime": now - (1 * _DAY_SECONDS), "last_modified": 1.0},
    ]

    first_new = 0
    trials = 100
    for _ in range(trials):
        shuffled = PlaylistManager._shuffle_age_weighted(rows, 365.0)
        if shuffled[0]["id"] == "new-capture":
            first_new += 1
    assert first_new > int(trials * 0.9)


def test_age_weighted_missing_timestamps_treated_as_newest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows with no timestamp at all are age 0 (newest), so appear early."""
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {"id": "no-ts"},
        {"id": "old", "last_modified": now - (2000 * _DAY_SECONDS)},
    ]
    first_no_ts = 0
    trials = 100
    for _ in range(trials):
        shuffled = PlaylistManager._shuffle_age_weighted(rows, 365.0)
        if shuffled[0]["id"] == "no-ts":
            first_no_ts += 1
    assert first_no_ts > int(trials * 0.9)


def test_age_weighted_smaller_half_life_is_stronger_bias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A smaller half-life should bias more aggressively toward newer media."""
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {"id": "old", "last_modified": now - (60 * _DAY_SECONDS)},
        {"id": "new", "last_modified": now - (1 * _DAY_SECONDS)},
    ]
    trials = 200

    strong_first_new = sum(
        1
        for _ in range(trials)
        if PlaylistManager._shuffle_age_weighted(rows, recency_half_life_days=7.0)[0]["id"] == "new"
    )
    weak_first_new = sum(
        1
        for _ in range(trials)
        if PlaylistManager._shuffle_age_weighted(rows, recency_half_life_days=3650.0)[0]["id"]
        == "new"
    )
    # A 7-day half-life biases far more strongly than a 10-year half-life.
    assert strong_first_new > weak_first_new


def test_age_weighted_weight_underflow_sorts_old_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When 0.5**(age/half_life) underflows to 0.0, the old row sorts LAST.

    Regression test: the weight underflows to zero for very old media or a very
    small half-life. The fallback key must be -inf (sorts last in descending
    order), preserving the recency bias. The earlier +inf fallback sorted the
    underflowed oldest row FIRST, inverting the intent.
    """
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {"id": "new", "last_modified": now - (1 * _DAY_SECONDS)},
        {"id": "very-old", "last_modified": now - (3 * 365 * _DAY_SECONDS)},
    ]

    # 1-day half-life: 0.5 ** 1095 underflows to 0.0 for the 3-year-old row.
    shuffled = PlaylistManager._shuffle_age_weighted(rows, recency_half_life_days=1.0)
    assert shuffled[0]["id"] == "new"
    assert shuffled[-1]["id"] == "very-old"


def test_age_weighted_runs_before_portrait_pair_joining(
    mock_media_repo: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Age-weighted shuffle operates on raw rows, before portrait-pair joining."""
    now = 1_700_000_000.0
    monkeypatch.setattr("picframe.core.services.playlist.time.time", lambda: now)
    rows = [
        {
            "id": 1,
            "filepath": "/path/to/portrait_new.jpg",
            "filename": "portrait_new.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": now - (1 * _DAY_SECONDS),
            "is_portrait": 1,
        },
        {
            "id": 2,
            "filepath": "/path/to/portrait_old.jpg",
            "filename": "portrait_old.jpg",
            "directory_id": 1,
            "media_type": "image",
            "file_size": 1024,
            "last_modified": now - (365 * _DAY_SECONDS),
            "is_portrait": 1,
        },
    ]
    mock_media_repo.query_media.return_value = rows
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.shuffle_mode": SHUFFLE_MODE_AGE_WEIGHTED,
        "model.recency_half_life_days": 30.0,
        "model.sample_limit": None,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.shuffle": True,
        "model.portrait_pairs": True,
    }.get(key, default)

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    criteria = mock_media_repo.query_media.call_args[0][0]
    assert criteria.shuffle_mode == SHUFFLE_MODE_AGE_WEIGHTED
    assert criteria.recency_half_life_days == 30.0
    assert criteria.sample_limit is None
    # The newer portrait should be in the first display slot.
    assert manager._display_playlist[0][0]["id"] == 1


def test_age_weighted_criteria_reads_config_keys(mock_media_repo: Mock) -> None:
    rows = [{"id": 1, "filepath": "/p/a.jpg", "last_modified": 1.0}]
    mock_media_repo.query_media.return_value = rows
    config_repo = Mock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.shuffle_mode": SHUFFLE_MODE_AGE_WEIGHTED,
        "model.recency_half_life_days": 90.0,
        "model.sample_limit": 50,
        "model.pic_dir": "/pictures",
    }.get(key, default)
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "model.shuffle": True,
        "model.portrait_pairs": False,
    }.get(key, default)

    manager = PlaylistManager(mock_media_repo, config_repo)
    manager.build_playlist()

    criteria = mock_media_repo.query_media.call_args[0][0]
    assert criteria.shuffle_mode == SHUFFLE_MODE_AGE_WEIGHTED
    assert criteria.recency_half_life_days == 90.0
    assert criteria.sample_limit == 50
    assert manager._shuffle_mode == SHUFFLE_MODE_AGE_WEIGHTED


def test_age_weighted_does_not_use_sql_random_order_clause() -> None:
    """age_weighted shuffles in Python, so the SQL order clause must avoid RANDOM()."""
    from picframe.core.repositories.sqlite_media import SQLiteMediaRepository

    clause = SQLiteMediaRepository._build_order_clause(
        PlaylistCriteria(shuffle=True, shuffle_mode=SHUFFLE_MODE_AGE_WEIGHTED)
    )
    assert "RANDOM()" not in clause
    assert "m.filepath ASC" in clause


def test_age_weighted_default_criteria_values() -> None:
    criteria = PlaylistCriteria(shuffle_mode=SHUFFLE_MODE_AGE_WEIGHTED)
    assert criteria.recency_half_life_days == 365.0
    assert criteria.sample_limit is None


def test_normalize_shuffle_mode_accepts_age_weighted() -> None:
    from picframe.core.models.playlist import normalize_shuffle_mode

    assert normalize_shuffle_mode("age_weighted") == SHUFFLE_MODE_AGE_WEIGHTED
    assert SHUFFLE_MODE_AGE_WEIGHTED in {
        SHUFFLE_MODE_STANDARD,
        SHUFFLE_MODE_FEWER_REPEATS,
        SHUFFLE_MODE_AGE_WEIGHTED,
    }
