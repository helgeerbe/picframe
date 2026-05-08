from unittest.mock import MagicMock, patch

import pytest

from picframe.core.metadata.video_strategy import VideoMetadataStrategy
from picframe.core.models.media import MediaType


@pytest.fixture
def strategy() -> VideoMetadataStrategy:
    return VideoMetadataStrategy()

@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_success(mock_stat: MagicMock, mock_run: MagicMock, mock_extract: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Mock os.stat
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1600000000.0
    mock_stat.return_value = mock_stat_result

    # Mock subprocess.run for ffprobe
    mock_run_result = MagicMock()
    mock_run_result.stdout = """
    {
        "format": {
            "duration": "120.5",
            "bit_rate": "5000000",
            "tags": {
                "creation_time": "2023-10-27T15:30:00.000000Z",
                "location": "+37.7749-122.4194/",
                "make": "Apple",
                "model": "iPhone 13 Pro",
                "title": "My Vacation",
                "description": "A nice trip",
                "keywords": "vacation, trip"
            }
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "pix_fmt": "yuv420p10le",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "60000/1001",
                "tags": {
                    "rotate": "90"
                }
            }
        ]
    }
    """
    mock_run.return_value = mock_run_result

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
    assert media_item.width == 1920
    assert media_item.height == 1080
    assert media_item.orientation == 6
    assert media_item.duration == 120.5
    assert media_item.codec == "hevc"
    assert media_item.pixel_format == "yuv420p10le"
    assert media_item.framerate == pytest.approx(59.94, 0.01)
    assert media_item.bitrate == 5000000
    assert media_item.latitude == 37.7749
    assert media_item.longitude == -122.4194
    assert media_item.make == "Apple"
    assert media_item.model == "iPhone 13 Pro"
    assert media_item.title == "My Vacation"
    assert media_item.caption == "A nice trip"
    assert media_item.tags == "vacation, trip"
    assert media_item.exif_datetime is not None
    mock_extract.assert_called_once_with(filepath, 120.5, 1920, 1080)

@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_exception_fallback(mock_stat: MagicMock, mock_run: MagicMock, mock_extract: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Mock subprocess.run to raise an exception
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")

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
    mock_extract.assert_not_called()

@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_os_error(mock_stat: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Make os.stat raise an OSError
    mock_stat.side_effect = OSError("File not found")

    filepath = "/path/to/missing.mp4"
    directory_id = 4

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is None
