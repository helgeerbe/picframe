from unittest.mock import Mock, patch

import pytest

from picframe.core.models.media import MediaItem, MediaType
from picframe.core.models.playlist import PlaylistCriteria
from picframe.core.repositories.interfaces import IMediaRepository
from picframe.core.services.playlist import PlaylistManager


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
    repo.record_media_displayed.side_effect = lambda media_id: next(
        (item for item in repo.get_all_media.return_value if item["id"] == media_id),
        None,
    )
    return repo


def test_build_playlist_no_shuffle(mock_media_repo: Mock) -> None:
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)
    
    assert len(manager._playlist) == 3
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

@patch('os.path.isfile', return_value=True)
def test_get_next(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)
    
    item1 = manager.get_next()
    assert isinstance(item1, MediaItem)
    assert item1.id == 1
    assert item1.media_type == MediaType.IMAGE
    mock_media_repo.record_media_displayed.assert_called_once_with(1)
    
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


@patch('os.path.isfile', return_value=True)
def test_get_previous(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)
    
    # No history yet
    assert manager.get_previous() is None
    
    manager.get_next() # id 1
    # Only 1 item in history, no previous
    assert manager.get_previous() is None
    
    manager.get_next() # id 2
    manager.get_next() # id 3
    
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


@patch('os.path.isfile', return_value=True)
def test_get_next_after_previous(mock_isfile: Mock, mock_media_repo: Mock) -> None:
    manager = PlaylistManager(mock_media_repo)
    manager.build_playlist(shuffle=False)
    
    manager.get_next() # id 1
    manager.get_next() # id 2
    manager.get_next() # id 3
    
    manager.get_previous() # returns 2
    
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
    assert criteria.sort_cols == "rating DESC"
    assert criteria.recent_n == 14
    assert manager._reshuffle_num == 3
