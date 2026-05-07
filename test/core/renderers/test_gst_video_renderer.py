from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import PlaybackCompletedEvent, SystemErrorEvent
from picframe.core.models.media import MediaItem, MediaType
from picframe.core.renderers.gst_video_renderer import GstVideoRenderer


@pytest.fixture
def mock_publisher() -> MagicMock:
    return MagicMock()

@pytest.fixture
def media_item() -> MediaItem:
    return MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        filename="video.mp4",
        directory_id=1,
        media_type=MediaType.VIDEO,
        file_size=1000,
        last_modified=1000.0,
        exif_datetime=1000.0,
        width=1280,
        height=720,
        orientation=1,
        title="Test Video",
        caption="",
        location="",
        tags="",
        is_portrait=False,
        codec="h264"
    )

@patch("picframe.core.renderers.gst_video_renderer.is_hardware_supported", return_value=True)
@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_play_video(mock_gst: MagicMock, mock_hw_supported: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_pipeline = MagicMock()
    mock_gst.Pipeline.new.return_value = mock_pipeline
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer._create_sink_bin = MagicMock()
    renderer.play(media_item)
    
    mock_gst.Pipeline.new.assert_called_once_with("video-player")
    mock_pipeline.set_state.assert_called_with(mock_gst.State.PLAYING)
    assert renderer._current_media == media_item

@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", False)
def test_play_video_gst_unavailable(mock_publisher: MagicMock, media_item: MediaItem) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item)
    
    mock_publisher.publish.assert_called_once()
    assert isinstance(mock_publisher.publish.call_args[0][0], PlaybackCompletedEvent)

@patch("picframe.core.renderers.gst_video_renderer.is_hardware_supported", return_value=True)
@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_stop_video(mock_gst: MagicMock, mock_hw_supported: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_pipeline = MagicMock()
    mock_bus = MagicMock()
    mock_bus.poll.return_value = False
    mock_pipeline.get_bus.return_value = mock_bus
    mock_gst.Pipeline.new.return_value = mock_pipeline
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer._create_sink_bin = MagicMock()
    renderer.play(media_item)
    renderer.stop()
    
    mock_pipeline.set_state.assert_called_with(mock_gst.State.NULL)
    assert renderer._pipeline is None
    assert renderer._current_media is None

@patch("picframe.core.renderers.gst_video_renderer.is_hardware_supported", return_value=True)
@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_pause_resume_video(
    mock_gst: MagicMock, mock_hw_supported: MagicMock, mock_publisher: MagicMock, media_item: MediaItem
) -> None:
    mock_pipeline = MagicMock()
    mock_gst.Pipeline.new.return_value = mock_pipeline
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer._create_sink_bin = MagicMock()
    renderer.play(media_item)
    
    renderer.pause()
    mock_pipeline.set_state.assert_called_with(mock_gst.State.PAUSED)
    
    renderer.resume()
    mock_pipeline.set_state.assert_called_with(mock_gst.State.PLAYING)

@patch("picframe.core.renderers.gst_video_renderer.is_hardware_supported", return_value=True)
@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_set_volume(mock_gst: MagicMock, mock_hw_supported: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_pipeline = MagicMock()
    mock_gst.Pipeline.new.return_value = mock_pipeline
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer._create_sink_bin = MagicMock()
    renderer.play(media_item)
    
    renderer.set_volume(0.5)
    mock_pipeline.set_property.assert_called_with("volume", 0.5)
    
    # Test bounds
    renderer.set_volume(1.5)
    mock_pipeline.set_property.assert_called_with("volume", 1.0)
    
    renderer.set_volume(-0.5)
    mock_pipeline.set_property.assert_called_with("volume", 0.0)

@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_on_eos(mock_gst: MagicMock, mock_publisher: MagicMock) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    renderer._on_eos(MagicMock(), MagicMock())
    
    mock_publisher.publish.assert_called_once()
    assert isinstance(mock_publisher.publish.call_args[0][0], PlaybackCompletedEvent)

@patch("picframe.core.renderers.gst_video_renderer.GST_AVAILABLE", True)
@patch("picframe.core.renderers.gst_video_renderer.Gst")
def test_on_error(mock_gst: MagicMock, mock_publisher: MagicMock) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    mock_msg = MagicMock()
    mock_err = MagicMock()
    mock_err.message = "Test Error"
    mock_msg.parse_error.return_value = (mock_err, "Debug Info")
    
    renderer._on_error(MagicMock(), mock_msg)
    
    assert mock_publisher.publish.call_count == 2
    assert isinstance(mock_publisher.publish.call_args_list[0][0][0], SystemErrorEvent)
    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], PlaybackCompletedEvent)
