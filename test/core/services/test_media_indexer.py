from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from picframe.core.events.dto import Command, CommandEvent, FileChangeEvent
from picframe.core.models.media import MediaItem, MediaType
from picframe.core.ports.media_monitor import IMediaMonitor
from picframe.core.services.media_indexer import MediaIndexerService


@pytest.fixture
def mock_media_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_media_by_path.return_value = None
    return repo


@pytest.fixture
def mock_config_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_event_subscriber() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_image_strategy() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_video_strategy() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_image_processing_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_media_monitor_service() -> MagicMock:
    return MagicMock(spec=IMediaMonitor)


@pytest.fixture
def media_indexer(
    mock_media_repo: MagicMock,
    mock_config_repo: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_image_strategy: MagicMock,
    mock_video_strategy: MagicMock,
    mock_image_processing_service: MagicMock,
    mock_media_monitor_service: MagicMock,
) -> Generator[MediaIndexerService, None, None]:
    # Setup config repo to return some extensions
    mock_config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.pic_dir": "/pictures",
        "model.image_extensions": [".jpg", ".jpeg", ".png"],
        "model.video_extensions": [".mp4", ".mov"],
    }.get(key, default)
    mock_config_repo.get_app_config_bool.side_effect = lambda key, default=None: {
        "model.follow_links": False,
    }.get(key, default)

    service = MediaIndexerService(
        media_repository=mock_media_repo,
        config_repository=mock_config_repo,
        event_subscriber=mock_event_subscriber,
        image_strategy=mock_image_strategy,
        video_strategy=mock_video_strategy,
        image_processing_service=mock_image_processing_service,
        media_monitor_service=mock_media_monitor_service,
    )
    yield service
    service.stop()


def test_handle_file_change_image(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_video_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    # Setup
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    file_stat = image_path.stat()
    event = FileChangeEvent(path=str(image_path), event_type="created")
    mock_media_item = MediaItem(
        filepath=str(image_path),
        directory_id=1,
        filename=image_path.name,
        media_type=MediaType.IMAGE,
        file_size=file_stat.st_size,
        last_modified=file_stat.st_mtime,
    )
    mock_image_strategy.extract.return_value = mock_media_item

    # Mock directory ID creation
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    # Execute
    media_indexer._handle_file_change(event)

    # Assert
    mock_image_strategy.extract.assert_called_once_with(str(image_path), 1)
    mock_video_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_called_once_with(mock_media_item.to_dict())


def test_handle_file_change_video(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_video_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    # Setup
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    file_stat = video_path.stat()
    event = FileChangeEvent(path=str(video_path), event_type="created")
    mock_media_item = MediaItem(
        filepath=str(video_path),
        directory_id=1,
        filename=video_path.name,
        media_type=MediaType.VIDEO,
        file_size=file_stat.st_size,
        last_modified=file_stat.st_mtime,
    )
    mock_video_strategy.extract.return_value = mock_media_item

    # Mock directory ID creation
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    # Execute
    media_indexer._handle_file_change(event)

    # Assert
    mock_video_strategy.extract.assert_called_once_with(str(video_path), 1)
    mock_image_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_called_once_with(mock_media_item.to_dict())


def test_handle_file_change_invalid_video_marks_inactive(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_video_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "broken.mp4"
    video_path.write_bytes(b"not a complete mp4")
    event = FileChangeEvent(path=str(video_path), event_type="created")
    mock_video_strategy.extract.return_value = None
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    media_indexer._handle_file_change(event)

    mock_video_strategy.extract.assert_called_once_with(str(video_path), 1)
    mock_image_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_not_called()
    mock_media_repo.delete_media_by_path.assert_called_once_with(str(video_path))


def test_handle_file_change_skips_unchanged_active_file(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "unchanged.jpg"
    image_path.write_bytes(b"image")
    file_stat = image_path.stat()
    mock_media_repo.get_media_by_path.return_value = {
        "filepath": str(image_path),
        "file_size": file_stat.st_size,
        "last_modified": file_stat.st_mtime,
        "is_deleted": 0,
    }

    media_indexer._handle_file_change(FileChangeEvent(path=str(image_path), event_type="created"))

    mock_image_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_not_called()


def test_handle_file_change_revalidates_video_with_incomplete_metadata(
    media_indexer: MediaIndexerService,
    mock_video_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "placeholder.mp4"
    video_path.write_bytes(b"video")
    file_stat = video_path.stat()
    mock_media_repo.get_media_by_path.return_value = {
        "filepath": str(video_path),
        "file_size": file_stat.st_size,
        "last_modified": file_stat.st_mtime,
        "is_deleted": 0,
        "media_type": "video",
        "duration": 0.0,
        "codec": None,
    }
    mock_media_item = MediaItem(
        filepath=str(video_path),
        directory_id=1,
        filename=video_path.name,
        media_type=MediaType.VIDEO,
        file_size=file_stat.st_size,
        last_modified=file_stat.st_mtime,
        duration=10.0,
        codec="h264",
    )
    mock_video_strategy.extract.return_value = mock_media_item
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    media_indexer._handle_file_change(FileChangeEvent(path=str(video_path), event_type="created"))

    mock_video_strategy.extract.assert_called_once_with(str(video_path), 1)
    mock_media_repo.add_media_item.assert_called_once_with(mock_media_item.to_dict())


def test_handle_file_change_reindexes_changed_file(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "changed.jpg"
    image_path.write_bytes(b"image")
    file_stat = image_path.stat()
    mock_media_repo.get_media_by_path.return_value = {
        "filepath": str(image_path),
        "file_size": file_stat.st_size + 1,
        "last_modified": file_stat.st_mtime,
        "is_deleted": 0,
    }
    mock_media_item = MediaItem(
        filepath=str(image_path),
        directory_id=1,
        filename=image_path.name,
        media_type=MediaType.IMAGE,
        file_size=file_stat.st_size,
        last_modified=file_stat.st_mtime,
    )
    mock_image_strategy.extract.return_value = mock_media_item
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    media_indexer._handle_file_change(FileChangeEvent(path=str(image_path), event_type="modified"))

    mock_image_strategy.extract.assert_called_once_with(str(image_path), 1)
    mock_media_repo.add_media_item.assert_called_once_with(mock_media_item.to_dict())


def test_handle_file_change_reindexes_restored_inactive_file(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "restored.jpg"
    image_path.write_bytes(b"image")
    file_stat = image_path.stat()
    mock_media_repo.get_media_by_path.return_value = {
        "filepath": str(image_path),
        "file_size": file_stat.st_size,
        "last_modified": file_stat.st_mtime,
        "is_deleted": 1,
    }
    mock_media_item = MediaItem(
        filepath=str(image_path),
        directory_id=1,
        filename=image_path.name,
        media_type=MediaType.IMAGE,
        file_size=file_stat.st_size,
        last_modified=file_stat.st_mtime,
    )
    mock_image_strategy.extract.return_value = mock_media_item
    media_indexer._get_or_create_directory_id = MagicMock(return_value=1)  # type: ignore

    media_indexer._handle_file_change(FileChangeEvent(path=str(image_path), event_type="created"))

    mock_image_strategy.extract.assert_called_once_with(str(image_path), 1)
    mock_media_repo.add_media_item.assert_called_once_with(mock_media_item.to_dict())


def test_handle_file_change_marks_missing_file_inactive(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_media_repo: MagicMock,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.jpg"

    media_indexer._handle_file_change(
        FileChangeEvent(path=str(missing_path), event_type="modified")
    )

    mock_image_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_not_called()
    mock_media_repo.delete_media_by_path.assert_called_once_with(str(missing_path))


def test_handle_file_change_unsupported_extension(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_video_strategy: MagicMock,
    mock_media_repo: MagicMock,
) -> None:
    # Setup
    event = FileChangeEvent(path="/test/document.txt", event_type="created")

    # Execute
    media_indexer._handle_file_change(event)

    # Assert
    mock_image_strategy.extract.assert_not_called()
    mock_video_strategy.extract.assert_not_called()
    mock_media_repo.add_media_item.assert_not_called()


def test_handle_file_change_deleted(
    media_indexer: MediaIndexerService, mock_media_repo: MagicMock
) -> None:
    # Setup
    event = FileChangeEvent(path="/test/image.jpg", event_type="deleted")

    # Execute
    media_indexer._handle_file_change(event)

    # Assert
    mock_media_repo.delete_media_by_path.assert_called_once_with("/test/image.jpg")


def test_handle_command_set_config(
    media_indexer: MediaIndexerService,
    mock_media_repo: MagicMock,
    mock_config_repo: MagicMock,
    mock_media_monitor_service: MagicMock,
) -> None:
    # Setup
    mock_config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.pic_dir": "/new/pic/dir",
        "model.image_extensions": [".jpg", ".jpeg", ".png"],
        "model.video_extensions": [".mp4", ".mov"],
    }.get(key, default)
    event = CommandEvent(command=Command.SET_CONFIG, payload={"model": {"pic_dir": "/new/pic/dir"}})

    # Execute
    media_indexer._handle_command(event)

    # Assert
    mock_media_monitor_service.configure.assert_called_once_with(
        directories=["/new/pic/dir"],
        allowed_extensions={".jpg", ".jpeg", ".png", ".mp4", ".mov"},
        follow_links=False,
    )
    mock_media_monitor_service.perform_differential_sync.assert_called_once()
    mock_media_repo.purge_missing_files.assert_not_called()


def test_handle_command_reloads_media_monitor_without_sync_for_follow_links(
    media_indexer: MediaIndexerService,
    mock_media_monitor_service: MagicMock,
    mock_config_repo: MagicMock,
) -> None:
    mock_config_repo.get_app_config_bool.side_effect = lambda key, default=None: {
        "model.follow_links": True,
    }.get(key, default)

    media_indexer._handle_command(
        CommandEvent(command=Command.SET_CONFIG, payload={"model": {"follow_links": True}})
    )

    mock_media_monitor_service.configure.assert_called_once_with(
        directories=["/pictures"],
        allowed_extensions={".jpg", ".jpeg", ".png", ".mp4", ".mov"},
        follow_links=True,
    )
    mock_media_monitor_service.perform_differential_sync.assert_not_called()


def test_pause_resume_stop_lifecycle(
    media_indexer: MediaIndexerService,
    mock_image_strategy: MagicMock,
    mock_image_processing_service: MagicMock,
    mock_media_monitor_service: MagicMock,
) -> None:
    media_indexer.pause()
    media_indexer._handle_file_change(FileChangeEvent(path="/test/image.jpg", event_type="created"))

    mock_media_monitor_service.pause.assert_called_once()
    mock_image_processing_service.pause.assert_called_once()
    mock_image_strategy.extract.assert_not_called()

    media_indexer.resume()
    mock_image_processing_service.resume.assert_called_once()
    mock_media_monitor_service.resume.assert_called_once()

    media_indexer.stop()
    media_indexer.stop()
    mock_media_monitor_service.stop.assert_called_once()
