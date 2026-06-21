import json
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.events.dto import (
    PlaybackCompletedEvent,
    SystemErrorEvent,
    VideoPlaybackDiagnosticsEvent,
    VideoPlaybackWarningEvent,
)
from picframe.core.models.media import MediaItem, MediaType
from picframe.core.renderers.gst_video_renderer import GstVideoRenderer
from picframe.core.renderers.ipc_protocol import (
    EosEvent,
    ErrorEvent,
    PlayCommand,
    VideoDiagnosticsEvent,
    WarningEvent,
    parse_ipc_message,
)


@pytest.fixture
def mock_publisher() -> MagicMock:
    return MagicMock()


@pytest.fixture(autouse=True)
def disable_listener_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests from starting the renderer's IPC listener thread.

    The connection object is mocked in this module, so the real listener loop
    would spin against MagicMock return values and leak CPU/memory across the
    test process. Event translation is tested directly through _handle_event().
    """
    monkeypatch.setattr(GstVideoRenderer, "_listen_for_events", lambda self: None)


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
def test_worker_environment_enables_v4l2_probe_on_pi(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client.return_value = MagicMock()
    monkeypatch.delenv("GST_V4L2_ENABLE_PROBE", raising=False)
    monkeypatch.setattr(
        GstVideoRenderer,
        "_is_raspberry_pi_hardware",
        staticmethod(lambda: True),
    )

    GstVideoRenderer(mock_publisher)

    env = mock_popen.call_args.kwargs["env"]
    assert env["GST_V4L2_ENABLE_PROBE"] == "1"


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_worker_environment_preserves_existing_v4l2_probe_value(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client.return_value = MagicMock()
    monkeypatch.setenv("GST_V4L2_ENABLE_PROBE", "0")
    monkeypatch.setattr(
        GstVideoRenderer,
        "_is_raspberry_pi_hardware",
        staticmethod(lambda: True),
    )

    GstVideoRenderer(mock_publisher)

    env = mock_popen.call_args.kwargs["env"]
    assert env["GST_V4L2_ENABLE_PROBE"] == "0"


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_worker_environment_does_not_force_v4l2_probe_off_pi(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client.return_value = MagicMock()
    monkeypatch.delenv("GST_V4L2_ENABLE_PROBE", raising=False)
    monkeypatch.setattr(
        GstVideoRenderer,
        "_is_raspberry_pi_hardware",
        staticmethod(lambda: False),
    )

    GstVideoRenderer(mock_publisher)

    env = mock_popen.call_args.kwargs["env"]
    assert "GST_V4L2_ENABLE_PROBE" not in env


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_play_video(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
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
    assert play_dict["max_software_decode_resolution"] == "1280x720"
    assert play_dict["fit_display"] is False
    assert play_dict["host_background"] is None


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_play_video_sends_fit_display(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn

    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item, fit_display=True)

    play_json = mock_conn.send.call_args_list[1][0][0]
    assert json.loads(play_json)["fit_display"] is True


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_play_video_sends_host_background(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn

    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item, host_background=(0.2, 0.2, 0.3, 1.0))

    play_json = mock_conn.send.call_args_list[1][0][0]
    assert json.loads(play_json)["host_background"] == [0.2, 0.2, 0.3, 1.0]


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_play_video_sends_host_backdrop(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn

    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(
        media_item,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )

    play_json = mock_conn.send.call_args_list[1][0][0]
    play_dict = json.loads(play_json)
    assert play_dict["host_backdrop_path"] == "/cache/video.1.frame"
    assert play_dict["host_backdrop_rect"] == [10, 20, 1000, 800]
    assert play_dict["content_fit"] == "fill"


def test_parse_play_command_preserves_host_background() -> None:
    command = parse_ipc_message(
        json.dumps(
            {
                "type": "play",
                "uri": "file:///path/to/video.mp4",
                "host_background": [0.2, 0.2, 0.3, 1.0],
                "host_backdrop_path": "/cache/video.1.frame",
                "host_backdrop_rect": [10, 20, 1000, 800],
                "content_fit": "fill",
            }
        )
    )

    assert isinstance(command, PlayCommand)
    assert command.host_background == [0.2, 0.2, 0.3, 1.0]
    assert command.host_backdrop_path == "/cache/video.1.frame"
    assert command.host_backdrop_rect == [10, 20, 1000, 800]
    assert command.content_fit == "fill"


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_set_max_software_decode_resolution_updates_future_play_commands(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn

    renderer = GstVideoRenderer(mock_publisher)
    renderer.set_max_software_decode_resolution("1920x1080")
    renderer.play(media_item)

    play_json = mock_conn.send.call_args_list[1][0][0]
    assert json.loads(play_json)["max_software_decode_resolution"] == "1920x1080"


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_stop_video(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(media_item, fit_display=True)
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
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
    mock_conn = MagicMock()
    mock_client.return_value = mock_conn
    
    renderer = GstVideoRenderer(mock_publisher)
    renderer.play(
        media_item,
        100,
        80,
        640,
        360,
        fit_display=True,
        host_background=(0.2, 0.2, 0.3, 1.0),
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )
    mock_conn.send.reset_mock()
    
    renderer.pause()
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    assert json.loads(sent_json)["type"] == "pause"
    
    mock_conn.send.reset_mock()
    renderer.resume()
    mock_conn.send.assert_called_once()
    sent_json = mock_conn.send.call_args[0][0]
    sent_dict = json.loads(sent_json)
    assert sent_dict["type"] == "play"
    assert sent_dict["x"] == 100
    assert sent_dict["y"] == 80
    assert sent_dict["w"] == 640
    assert sent_dict["h"] == 360
    assert sent_dict["fit_display"] is True
    assert sent_dict["host_background"] == [0.2, 0.2, 0.3, 1.0]
    assert sent_dict["host_backdrop_path"] == "/cache/video.1.frame"
    assert sent_dict["host_backdrop_rect"] == [10, 20, 1000, 800]
    assert sent_dict["content_fit"] == "fill"

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_set_volume(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
    media_item: MediaItem,
) -> None:
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
def test_handle_eos_event(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    
    event = EosEvent()
    renderer._handle_event(event)
    
    mock_publisher.publish.assert_called_once()
    assert isinstance(mock_publisher.publish.call_args[0][0], PlaybackCompletedEvent)


def test_parse_eos_event_with_last_sample_diagnostics() -> None:
    event = parse_ipc_message(
        json.dumps(
            {
                "type": "eos",
                "last_sample_pts_seconds": 27.92,
                "last_sample_duration_seconds": 0.04,
                "last_sample_caps": "video/x-raw(memory:DMABuf)",
            }
        )
    )

    assert isinstance(event, EosEvent)
    assert event.last_sample_pts_seconds == 27.92
    assert event.last_sample_duration_seconds == 0.04
    assert event.last_sample_caps == "video/x-raw(memory:DMABuf)"

@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_error_event(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)
    
    event = ErrorEvent(details="Test Error", code="pipeline_failed")
    renderer._handle_event(event)
    
    assert mock_publisher.publish.call_count == 2
    assert isinstance(mock_publisher.publish.call_args_list[0][0][0], SystemErrorEvent)
    assert mock_publisher.publish.call_args_list[0][0][0].message == "Test Error"
    assert mock_publisher.publish.call_args_list[0][0][0].code == "pipeline_failed"
    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], PlaybackCompletedEvent)


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_unsupported_media_error_publishes_warning_and_completion(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)

    event = ErrorEvent(details="Skipping video 1920x1080", code="unsupported_media")
    renderer._handle_event(event)

    assert mock_publisher.publish.call_count == 2
    warning = mock_publisher.publish.call_args_list[0][0][0]
    assert isinstance(warning, VideoPlaybackWarningEvent)
    assert warning.warning_type == "unsupported_media"
    assert warning.decoder == "Skipping video 1920x1080"
    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], PlaybackCompletedEvent)


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_gtk_presentation_error_publishes_system_error_and_completion(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)

    event = ErrorEvent(
        details="GTK4 video presentation is required",
        code="gtk_presentation_unavailable",
    )
    renderer._handle_event(event)

    assert mock_publisher.publish.call_count == 2
    error = mock_publisher.publish.call_args_list[0][0][0]
    assert isinstance(error, SystemErrorEvent)
    assert error.message == "GTK4 video presentation is required"
    assert error.code == "gtk_presentation_unavailable"
    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], PlaybackCompletedEvent)


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_warning_event_publishes_video_playback_warning(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)

    renderer._handle_event(
        WarningEvent(warning_type="software_fallback", decoder="avdec_h264")
    )

    mock_publisher.publish.assert_called_once()
    published_event = mock_publisher.publish.call_args[0][0]
    assert isinstance(published_event, VideoPlaybackWarningEvent)
    assert published_event.warning_type == "software_fallback"
    assert published_event.decoder == "avdec_h264"


@patch("picframe.core.renderers.gst_video_renderer.subprocess.Popen")
@patch("picframe.core.renderers.gst_video_renderer.Client")
@patch("picframe.core.renderers.gst_video_renderer.os.path.exists", return_value=True)
def test_handle_video_diagnostics_event_publishes_domain_event(
    mock_exists: MagicMock,
    mock_client: MagicMock,
    mock_popen: MagicMock,
    mock_publisher: MagicMock,
) -> None:
    renderer = GstVideoRenderer(mock_publisher)

    renderer._handle_event(
        VideoDiagnosticsEvent(
            pipeline_variant="hardware_direct",
            stage="caps",
            sink="waylandsink",
            decoder="v4l2h264dec",
            decoder_is_hardware=True,
            caps="video/x-raw(memory:DMABuf)",
            uses_dmabuf=True,
            hardware_limit="1920x1080@60",
            software_limit="1280x720",
            decision="hardware_direct",
        )
    )

    mock_publisher.publish.assert_called_once()
    published_event = mock_publisher.publish.call_args[0][0]
    assert isinstance(published_event, VideoPlaybackDiagnosticsEvent)
    assert published_event.pipeline_variant == "hardware_direct"
    assert published_event.stage == "caps"
    assert published_event.sink == "waylandsink"
    assert published_event.decoder == "v4l2h264dec"
    assert published_event.decoder_is_hardware is True
    assert published_event.uses_dmabuf is True
    assert published_event.hardware_limit == "1920x1080@60"
    assert published_event.software_limit == "1280x720"
    assert published_event.decision == "hardware_direct"
