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
def test_extract_success(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
    strategy: VideoMetadataStrategy,
) -> None:
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
def test_extract_passes_cache_dir_and_fit_mode(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
) -> None:
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1600000000.0
    mock_stat.return_value = mock_stat_result
    mock_run_result = MagicMock()
    mock_run_result.stdout = """
    {
        "format": {"duration": "10.0"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080
            }
        ]
    }
    """
    mock_run.return_value = mock_run_result
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config_bool.return_value = True
    mock_config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.background": [0.2, 0.2, 0.3, 1.0],
        "viewer.blur_amount": 8,
        "viewer.blur_zoom": 1.2,
        "viewer.edge_alpha": 0.5,
        "viewer.mat_images": "on",
        "viewer.mat_type": "double_flat",
        "viewer.outer_mat_color": [10, 20, 30],
        "viewer.inner_mat_color": [40, 50, 60],
        "viewer.outer_mat_border": 75,
        "viewer.inner_mat_border": 40,
        "viewer.outer_mat_use_texture": False,
        "viewer.inner_mat_use_texture": False,
        "viewer.mat_resource_folder": "/tmp/mat",
    }.get(key, default)
    mock_config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "viewer.video_fit_display": True,
        "viewer.blur_edges": True,
    }.get(key, default)
    strategy = VideoMetadataStrategy(
        display_w=1280,
        display_h=720,
        config_repository=mock_config_repo,
        cache_dir="/tmp/picframe-cache",
    )

    strategy.extract("/path/to/video.mp4", 1)

    mock_config_repo.get_app_config_bool.assert_any_call("viewer.video_fit_display", False)
    mock_config_repo.get_app_config_bool.assert_any_call("viewer.blur_edges", False)
    mock_config_repo.get_app_config.assert_any_call("viewer.background", None)
    mock_extract.assert_called_once_with(
        "/path/to/video.mp4",
        10.0,
        1280,
        720,
        fit_display=True,
        background=[0.2, 0.2, 0.3, 1.0],
        matting_config={
            "mat_images": "on",
            "mat_type": "double_flat",
            "outer_mat_color": [10, 20, 30],
            "inner_mat_color": [40, 50, 60],
            "outer_mat_border": 75,
            "inner_mat_border": 40,
            "outer_mat_use_texture": False,
            "inner_mat_use_texture": False,
            "mat_resource_folder": "/tmp/mat",
        },
        edge_config={
            "blur_edges": True,
            "blur_amount": 8,
            "blur_zoom": 1.2,
            "edge_alpha": 0.5,
        },
        cache_dir="/tmp/picframe-cache",
    )

@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_ffprobe_failure_returns_none(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
    strategy: VideoMetadataStrategy,
) -> None:
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 4096
    mock_stat_result.st_mtime = 1600000002.0
    mock_stat.return_value = mock_stat_result

    filepath = "/path/to/video3.avi"
    directory_id = 3

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is None
    mock_extract.assert_not_called()


@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_invalid_ffprobe_json_returns_none(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
    strategy: VideoMetadataStrategy,
) -> None:
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 4096
    mock_stat_result.st_mtime = 1600000002.0
    mock_stat.return_value = mock_stat_result
    mock_run_result = MagicMock()
    mock_run_result.stdout = "not json"
    mock_run.return_value = mock_run_result

    media_item = strategy.extract("/path/to/video.mp4", 1)

    assert media_item is None
    mock_extract.assert_not_called()


@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_no_video_stream_returns_none(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
    strategy: VideoMetadataStrategy,
) -> None:
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 4096
    mock_stat_result.st_mtime = 1600000002.0
    mock_stat.return_value = mock_stat_result
    mock_run_result = MagicMock()
    mock_run_result.stdout = """
    {
        "format": {"duration": "10.0"},
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac"
            }
        ]
    }
    """
    mock_run.return_value = mock_run_result

    media_item = strategy.extract("/path/to/audio_only.mp4", 1)

    assert media_item is None
    mock_extract.assert_not_called()


@patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.extract_and_save_frames")
@patch("picframe.core.metadata.video_strategy.subprocess.run")
@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_keeps_valid_video_when_frame_cache_fails(
    mock_stat: MagicMock,
    mock_run: MagicMock,
    mock_extract: MagicMock,
    strategy: VideoMetadataStrategy,
) -> None:
    mock_stat_result = MagicMock()
    mock_stat_result.st_size = 1024
    mock_stat_result.st_mtime = 1600000000.0
    mock_stat.return_value = mock_stat_result
    mock_run_result = MagicMock()
    mock_run_result.stdout = """
    {
        "format": {"duration": "10.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080
            }
        ]
    }
    """
    mock_run.return_value = mock_run_result
    mock_extract.return_value = False

    media_item = strategy.extract("/path/to/video.mp4", 1)

    assert media_item is not None
    assert media_item.media_type == MediaType.VIDEO
    assert media_item.codec == "h264"
    mock_extract.assert_called_once_with("/path/to/video.mp4", 10.0, 1920, 1080)

@patch("picframe.core.metadata.video_strategy.os.stat")
def test_extract_os_error(mock_stat: MagicMock, strategy: VideoMetadataStrategy) -> None:
    # Make os.stat raise an OSError
    mock_stat.side_effect = OSError("File not found")

    filepath = "/path/to/missing.mp4"
    directory_id = 4

    media_item = strategy.extract(filepath, directory_id)

    assert media_item is None
