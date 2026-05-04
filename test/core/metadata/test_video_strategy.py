from unittest.mock import MagicMock, patch

import pytest

from picframe.core.metadata.video_strategy import VideoMetadataStrategy
from picframe.core.models.media import MediaType


@pytest.fixture
def strategy() -> VideoMetadataStrategy:
    return VideoMetadataStrategy()

@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_success(mock_stat: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Mock os.stat
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1600000000.0
    mock_stat.return_value = mock_stat_result

    filepath = "/path/to/video.mp4"
    directory_id = 1

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is not None
    assert media_item.filepath == filepath
    assert media_item.directory_id == directory_id
    assert media_item.filename == "video.mp4"
    assert media_item.media_type == MediaType.VIDEO
    assert media_item.file_size == 1024
    assert media_item.last_modified == 1600000000.0
    assert media_item.width is None
    assert media_item.height is None
    assert media_item.orientation == 1
    assert media_item.duration == 0.0

@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_exception_fallback(mock_stat: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Mock os.stat to raise an exception on first call, then return a result for the fallback
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 4096
    mock_stat_result.st_mtime = 1600000002.0
    mock_stat.side_effect = [ValueError("Test exception"), mock_stat_result]

    filepath = "/path/to/video3.avi"
    directory_id = 3

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is not None
    assert media_item.filepath == filepath
    assert media_item.directory_id == directory_id
    assert media_item.filename == "video3.avi"
    assert media_item.media_type == MediaType.VIDEO
    assert media_item.file_size == 4096
    assert media_item.last_modified == 1600000002.0
    assert media_item.width is None
    assert media_item.height is None

@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_os_error(mock_stat: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Make os.stat raise an OSError
    mock_stat.side_effect = OSError("File not found")

    filepath = "/path/to/missing.mp4"
    directory_id = 4

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is None
