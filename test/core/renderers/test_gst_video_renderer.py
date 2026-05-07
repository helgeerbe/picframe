from unittest.mock import MagicMock, patch
import json

import pytest

from picframe.core.events.dto import PlaybackCompletedEvent, SystemErrorEvent
from picframe.core.models.media import MediaItem, MediaType
from picframe.core.renderers.gst_video_renderer import GstVideoRenderer
from picframe.core.renderers.ipc_protocol import (
    EosEvent,
    ErrorEvent,
    PauseCommand,
    PlayCommand,
    SetVolumeCommand,
    StopCommand,
    WarningEvent,
)


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

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_play_video(mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item)
    
    assert renderer._current_media == media_item
    assert mock_conn.send.call_count == 2
    
    # Verify the sent commands
    stop_json = mock_conn.send.call_args_list[0][0][0]
    stop_dict = json.loads(stop_json)
    assert stop_dict["type"] == "stop"

    play_json = mock_conn.send.call_args_list[1][0][0]
    play_dict = json.loads(play_json)
    assert play_dict["type"] == "play"
    assert "file:///path/to/video.mp4" in play_dict["uri"]

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_stop_video(mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item)
    mock_conn.send.reset_mock()
    
    renderer.stop()
    
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    sent_dict = json.loads(sent_json)
    assert sent_dict["type"] == "stop"
    assert renderer._current_media is None

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_pause_resume_video(
    mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock, media_item: MediaItem
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item)
    mock_conn.send.reset_mock()
    
    renderer.pause()
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    assert json.loads(sent_json)["type"] == "pause"
    
    mock_conn.send.reset_mock()
    renderer.resume()
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    assert json.loads(sent_json)["type"] == "play"

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_set_volume(mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock, media_item: MediaItem) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    
    renderer.set_volume(0.5)
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    sent_dict = json.loads(sent_json)
    assert sent_dict["type"] == "set_volume"
    assert sent_dict["level"] == 0.5
    
    mock_conn.send.reset_mock()
    renderer.set_volume(1.5)
    sent_json = mock_conn.send.call_args[0][0]
    assert json.loads(sent_json)["level"] == 1.0
    
    mock_conn.send.reset_mock()
    renderer.set_volume(-0.5)
    sent_json = mock_conn.send.call_args[0][0]
    assert json.loads(sent_json)["level"] == 0.0

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_eos_event(mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    
    event = EosEvent()
    renderer._handle_event(event)
    
    mock_publisher.publish.assert_called_once()
    assert isinstance(mock_publisher.publish.call_args[0][0], PlaybackCompletedEvent)

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_error_event(mock_exists: MagicMock, mock_client: MagicMock, mock_popen: MagicMock, mock_publisher: MagicMock) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    
    event = ErrorEvent(details="Test Error")
    renderer._handle_event(event)
    
    assert mock_publisher.publish.call_count == 2
    assert isinstance(mock_publisher.publish.call_args_list[0][0][0], SystemErrorEvent)
    assert mock_publisher.publish.call_args_list[0][0][0].message == "Test Error"
    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], PlaybackCompletedEvent)
