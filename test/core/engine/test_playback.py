"""
Unit tests for the PlaybackEngine.
"""
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.engine.playback import (
    PlaybackEngine,
    VIDEO_EOS_REDRAW_FRAMES,
    VIDEO_EOS_REDRAW_TIMEOUT_SECONDS,
)
from picframe.core.events.dto import (
    Command,
    CommandEvent,
    PlaybackCompletedEvent,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
    SystemErrorEvent,
    VideoPlaybackWarningEvent,
)
from picframe.core.models.media import DisplayItem, DisplayLayout, MediaItem, MediaType
from picframe.core.services.renderer_assets import RendererAssetIssue


@pytest.fixture
def mock_event_publisher() -> MagicMock:
    """Mock the event publisher."""
    return MagicMock()


@pytest.fixture
def mock_event_subscriber() -> MagicMock:
    """Mock the event subscriber."""
    return MagicMock()


@pytest.fixture
def mock_playlist_manager() -> MagicMock:
    """Mock the playlist manager."""
    manager = MagicMock()
    
    # Setup default media item
    media_item = MediaItem(
        id=1,
        filepath="/path/to/image.jpg",
        media_type=MediaType.IMAGE,
        filename="image.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    manager.get_next.return_value = media_item
    manager.get_previous.return_value = media_item
    
    return manager


@pytest.fixture
def mock_renderer() -> MagicMock:
    """Mock the renderer."""
    renderer = MagicMock()
    # Make render_frame return False after one call to avoid infinite loops in tests
    renderer.render_frame.side_effect = [True, False]
    return renderer


@pytest.fixture
def config() -> dict[str, Any]:
    """Default engine configuration."""
    return {
        "time_delay": 10.0,
        "video_extensions": [".mp4", ".mov", ".mkv", ".avi", ".webm"],
    }


class FakeTimer:
    def __init__(self, interval: float, callback) -> None:
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def test_engine_initialization(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test that the engine initializes correctly."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    
    assert engine._state == State.IDLE
    assert engine._is_running is False
    assert engine._time_delay == 10.0
    
    # Verify it subscribed to commands
    mock_event_subscriber.subscribe.assert_any_call(CommandEvent, engine._handle_command)
    mock_event_subscriber.subscribe.assert_any_call(StateEvent, engine._handle_state_event)


def test_engine_start_stop(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test starting and stopping the engine."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    
    # Mock _run_loop to return immediately so we don't block
    with patch.object(engine, "_run_loop"):
        engine.start()
        
        assert engine._is_running is True
        mock_renderer.start.assert_called_once()
        
        # Should have transitioned to PLAYING
        assert engine._state == State.PLAYING
        
        # Should have published state event
        mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PLAYING))
        
        # Should have set next transition time to 0.0 to force immediate transition in run_loop
        assert engine._next_transition_time == 0.0
        
        
        engine.stop()
        
        assert engine._is_running is False
        # renderer.stop() is now called at the end of _run_loop, not in stop()
        assert engine._state == State.IDLE


def test_engine_renderer_asset_failure_keeps_engine_alive(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    issue = RendererAssetIssue(
        field="viewer.shader",
        path="/missing/blend_new.vs",
        message="Missing shader .vs file",
    )
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        renderer_config=RendererConfig(shader_path="/missing/blend_new"),
        renderer_asset_validator=lambda _config: [issue],
    )

    with patch.object(engine, "_run_loop"):
        engine.start()

    assert engine._is_running is True
    assert engine._state == State.ERROR
    mock_renderer.start.assert_not_called()
    mock_playlist_manager.build_playlist.assert_not_called()
    mock_event_publisher.publish.assert_any_call(
        SystemErrorEvent(
            message="viewer.shader: Missing shader .vs file (/missing/blend_new.vs)",
            component="Pi3dRenderer",
            sticky=True,
            code="invalid_renderer_config",
        )
    )
    mock_event_publisher.publish.assert_any_call(
        StateEvent(
            state=State.ERROR,
            payload={
                "component": "Pi3dRenderer",
                "reason": "invalid_renderer_config",
                "message": "viewer.shader: Missing shader .vs file (/missing/blend_new.vs)",
            },
        )
    )


def test_engine_retries_renderer_start_after_config_update(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    renderer_config = RendererConfig(shader_path="/valid/blend_new")
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        renderer_config=RendererConfig(shader_path="/missing/blend_new"),
        renderer_asset_validator=lambda _config: [],
    )
    engine._is_running = True
    engine._state = State.ERROR
    mock_renderer.render_frame.side_effect = [False]
    engine._handle_renderer_config_event(RendererConfigUpdatedEvent(config=renderer_config))

    engine._run_loop()

    mock_renderer.start.assert_called_once()
    mock_playlist_manager.build_playlist.assert_called_once()
    assert engine._state == State.PLAYING


def test_engine_restarts_renderer_after_display_geometry_config_update(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        renderer_config=RendererConfig(
            display_x=0,
            display_y=80,
            display_w=1800,
            display_h=1000,
        ),
    )
    engine._renderer_started = True

    engine._handle_renderer_config_event(
        RendererConfigUpdatedEvent(
            config=RendererConfig(
                display_x=100,
                display_y=80,
                display_w=1800,
                display_h=1000,
            )
        )
    )

    assert engine._renderer_retry_requested is True


def test_engine_purge_does_not_rebuild_playlist_while_renderer_blocked(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    engine._state = State.ERROR
    mock_playlist_manager.purge_missing_files.return_value = 3

    engine._handle_purge_command()

    mock_playlist_manager.purge_missing_files.assert_called_once()
    mock_playlist_manager.build_playlist.assert_not_called()
    assert engine._playlist_ready is False


def test_engine_handle_command_next(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test handling the NEXT command."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    
    event = CommandEvent(command=Command.NEXT)
    engine._handle_command(event)
    
    mock_playlist_manager.get_next.assert_called_once()
    


def test_engine_handle_command_prev(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test handling the PREV command."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    
    event = CommandEvent(command=Command.PREV)
    engine._handle_command(event)
    
    mock_playlist_manager.get_previous.assert_called_once()
    


def test_engine_handle_command_pause_play(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test handling PAUSE and PLAY commands."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    
    # Start in PLAYING state
    engine._state = State.PLAYING
    
    # Pause
    event = CommandEvent(command=Command.PAUSE)
    engine._handle_command(event)
    
    assert engine._state == State.IDLE
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.IDLE))
    
    # Play
    event = CommandEvent(command=Command.PLAY)
    engine._handle_command(event)
    
    assert engine._state == State.PLAYING
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PLAYING))


def test_engine_handle_command_stop(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test handling the STOP command."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    engine._is_running = True
    engine._renderer_started = True
    
    event = CommandEvent(command=Command.STOP)
    engine._handle_command(event)
    
    assert engine._is_running is False
    # renderer.stop() is now called at the end of _run_loop, not in stop()
    assert engine._state == State.IDLE


def test_engine_trigger_next_media_portrait_pair_command(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    left = MediaItem(
        id=1,
        filepath="/path/to/left.jpg",
        media_type=MediaType.IMAGE,
        filename="left.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        is_portrait=True,
        title="Left",
    )
    right = MediaItem(
        id=2,
        filepath="/path/to/right.jpg",
        media_type=MediaType.IMAGE,
        filename="right.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        is_portrait=True,
        title="Right",
    )
    display_item = DisplayItem.portrait_pair(left, right)
    mock_playlist_manager.get_next.return_value = display_item
    config["show_text"] = "title"

    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )

    engine._trigger_next_media()

    render_cmd = mock_renderer.execute.call_args.args[0]
    assert render_cmd.layout == DisplayLayout.PORTRAIT_PAIR.value
    assert render_cmd.image_paths == ("/path/to/left.jpg", "/path/to/right.jpg")
    assert render_cmd.overlay.text_strings == ("Left", "Right")


def test_engine_pair_overlay_uses_next_gen_text_config(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    left = MediaItem(
        id=1,
        filepath="/path/to/left.jpg",
        media_type=MediaType.IMAGE,
        filename="left.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        is_portrait=True,
    )
    right = MediaItem(
        id=2,
        filepath="/path/to/right.jpg",
        media_type=MediaType.IMAGE,
        filename="right.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        is_portrait=True,
    )
    display_item = DisplayItem.portrait_pair(left, right)
    mock_playlist_manager.get_next.return_value = display_item
    config_repo = MagicMock()
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "viewer.show_clock": False,
        "viewer.show_text_enabled": True,
    }.get(key, default)
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.clock_format": "%H:%M",
        "viewer.text_overlay_format": "name",
        "viewer.show_text_fm": "%b %d, %Y",
    }.get(key, default)

    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    engine._trigger_next_media()

    render_cmd = mock_renderer.execute.call_args.args[0]
    assert render_cmd.overlay.show_text is True
    assert render_cmd.overlay.text_string == "left.jpg"
    assert render_cmd.overlay.text_strings == ("left.jpg", "right.jpg")


def test_engine_delete_pair_right_uses_payload(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    tmp_path: Path,
) -> None:
    left_file = tmp_path / "left.jpg"
    right_file = tmp_path / "right.jpg"
    left_file.write_bytes(b"left")
    right_file.write_bytes(b"right")
    deleted_dir = tmp_path / "deleted"
    left = MediaItem(
        id=1,
        filepath=str(left_file),
        media_type=MediaType.IMAGE,
        filename="left.jpg",
        directory_id=1,
        file_size=4,
        last_modified=1.0,
        is_portrait=True,
    )
    right = MediaItem(
        id=2,
        filepath=str(right_file),
        media_type=MediaType.IMAGE,
        filename="right.jpg",
        directory_id=1,
        file_size=5,
        last_modified=1.0,
        is_portrait=True,
    )
    display_item = DisplayItem.portrait_pair(left, right)
    mock_playlist_manager.get_current.return_value = display_item
    mock_playlist_manager.resolve_current_delete_ids.return_value = [2]
    config["deleted_pictures"] = str(deleted_dir)
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )

    with patch.object(engine, "_trigger_next_media"):
        engine._handle_delete_command({"target": "right", "media_ids": [2]})

    assert left_file.exists()
    assert not right_file.exists()
    assert (deleted_dir / "right.jpg").exists()
    mock_playlist_manager.resolve_current_delete_ids.assert_called_once_with("right", [2])
    mock_playlist_manager.delete_media_ids.assert_called_once_with([2])


def test_engine_delete_single_moves_file_and_removes_cache_row(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    tmp_path: Path,
) -> None:
    image_file = tmp_path / "image.jpg"
    image_file.write_bytes(b"image")
    deleted_dir = tmp_path / "deleted"
    media_item = MediaItem(
        id=1,
        filepath=str(image_file),
        media_type=MediaType.IMAGE,
        filename="image.jpg",
        directory_id=1,
        file_size=5,
        last_modified=1.0,
    )
    mock_playlist_manager.get_current.return_value = DisplayItem.single(media_item)
    mock_playlist_manager.resolve_current_delete_ids.return_value = [1]
    config["deleted_pictures"] = str(deleted_dir)
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )

    with patch.object(engine, "_trigger_next_media"):
        engine._handle_delete_command()

    assert not image_file.exists()
    assert (deleted_dir / "image.jpg").exists()
    mock_playlist_manager.delete_media_ids.assert_called_once_with([1])


def test_engine_delete_failed_move_leaves_cache_row(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    tmp_path: Path,
) -> None:
    image_file = tmp_path / "image.jpg"
    image_file.write_bytes(b"image")
    media_item = MediaItem(
        id=1,
        filepath=str(image_file),
        media_type=MediaType.IMAGE,
        filename="image.jpg",
        directory_id=1,
        file_size=5,
        last_modified=1.0,
    )
    mock_playlist_manager.get_current.return_value = DisplayItem.single(media_item)
    mock_playlist_manager.resolve_current_delete_ids.return_value = [1]
    config["deleted_pictures"] = str(tmp_path / "deleted")
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )

    with patch("shutil.move", side_effect=OSError("move failed")):
        engine._handle_delete_command()

    assert image_file.exists()
    mock_playlist_manager.delete_media_ids.assert_not_called()


def test_engine_rebuilds_playlist_and_updates_delay_on_model_config_change(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config_repo = MagicMock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.time_delay": 42.0,
        "model.fade_time": 4.0,
        "model.video_extensions": [".mp4"],
    }.get(key, default)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )
    engine._state = State.PLAYING
    engine._renderer_started = True
    engine._next_transition_time = 9999999999.0

    engine._handle_state_event(
        StateEvent(
            state=State.CONFIG_CHANGED,
            payload={"updated_sections": ["model"]},
        )
    )

    assert engine._time_delay == 42.0
    assert engine._config["fade_time"] == 4.0
    assert engine._config["video_extensions"] == [".mp4"]
    mock_playlist_manager.build_playlist.assert_called_once()


def test_engine_run_loop_exit(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test that the run loop exits when the renderer returns False."""
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    engine._is_running = True
    engine._renderer_started = True
    
    # Renderer is mocked to return True then False
    engine._run_loop()
    
    # Should have called render_frame twice
    assert mock_renderer.render_frame.call_count == 2
    
    # Should have stopped the engine
    assert engine._is_running is False
    mock_renderer.stop.assert_called_once()


def test_engine_trigger_next_media_video(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test that video files are correctly identified and routed to the video player."""
    mock_video_player = MagicMock()
    
    # Add video_extensions to config
    config["video_extensions"] = [".mp4", ".mov", ".mkv", ".avi", ".webm"]
    
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config, video_player=mock_video_player
    )
    
    # Setup a .mov media item
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.MOV",
        media_type=MediaType.VIDEO,
        filename="video.MOV",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (0, 0, 1920, 1080)
    media_item.duration = 10.0

    with patch("os.path.exists", return_value=True), \
         patch(
             "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
             return_value=(MagicMock(), MagicMock()),
         ) as mock_get_frames:
        engine._trigger_next_media()
    
    # Verify state changed to PREPARING_VIDEO
    assert engine._state == State.PREPARING_VIDEO
    
    # Verify renderer was sent the first frame
    from picframe.core.events.dto import RenderCommand
    call_args = mock_renderer.execute.call_args[0][0]
    assert isinstance(call_args, RenderCommand)
    assert call_args.image_path == "/path/to/video.1.frame"
    assert mock_get_frames.call_args.kwargs["extract_missing"] is False


def test_engine_trigger_next_media_video_uses_cache_dir(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    tmp_path: Path,
) -> None:
    mock_video_player = MagicMock()
    cache_dir = tmp_path / "cache"
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
        cache_dir=str(cache_dir),
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.MOV",
        media_type=MediaType.VIDEO,
        filename="video.MOV",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (0, 0, 1920, 1080)

    with patch("os.path.exists", return_value=True), \
         patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames", return_value=(MagicMock(), MagicMock())):
        engine._trigger_next_media()

    from picframe.core.events.dto import RenderCommand
    from picframe.core.utils.video_frame_extractor import VideoFrameExtractor

    expected_path = VideoFrameExtractor.get_cached_frame_path(
        media_item.filepath,
        1920,
        1080,
        False,
        "first",
        str(cache_dir),
    )
    call_args = mock_renderer.execute.call_args[0][0]
    assert isinstance(call_args, RenderCommand)
    assert call_args.image_path == expected_path


def test_engine_trigger_next_media_video_plays_directly_without_frames(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (10, 20, 1920, 1080)

    with patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=None,
    ):
        engine._trigger_next_media()

    from picframe.core.events.dto import RenderCommand

    render_cmd = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "RESUME"
    mock_video_player.play.assert_called_once_with(media_item, 10, 20, 1920, 1080)
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")


def test_engine_trigger_next_media_video_plays_directly_when_cached_frame_load_times_out(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    monkeypatch,
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (10, 20, 1920, 1080)
    release_loader = threading.Event()
    loader_entered = threading.Event()
    monkeypatch.setattr(
        "picframe.core.engine.playback.VIDEO_TRANSITION_FRAME_LOAD_TIMEOUT_SECONDS",
        0.01,
    )

    def block_cached_frame_load(*args: Any, **kwargs: Any) -> None:
        loader_entered.set()
        release_loader.wait(1.0)
        return None

    try:
        with patch(
            "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
            side_effect=block_cached_frame_load,
        ):
            engine._trigger_next_media()
    finally:
        assert loader_entered.wait(0.5)
        release_loader.set()

    from picframe.core.events.dto import RenderCommand

    render_cmd = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "RESUME"
    mock_video_player.play.assert_called_once_with(media_item, 10, 20, 1920, 1080)
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")


def test_engine_video_display_rect_prefers_configured_custom_rect(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config_repo = MagicMock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.display_x": 100,
        "viewer.display_y": 80,
        "viewer.display_w": "1800",
        "viewer.display_h": "1000",
    }.get(key, default)
    mock_renderer.get_display_rect.return_value = (0, 80, 1800, 1000)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    assert engine._video_display_rect() == (100, 80, 1800, 1000)


def test_engine_video_handoff_uses_configured_custom_rect(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    config_repo = MagicMock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.display_x": 100,
        "viewer.display_y": 80,
        "viewer.display_w": "1800",
        "viewer.display_h": "1000",
    }.get(key, default)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
        video_player=mock_video_player,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (0, 80, 1800, 1000)

    with patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=None,
    ):
        engine._trigger_next_media()

    mock_video_player.play.assert_called_once_with(
        media_item,
        100,
        80,
        1800,
        1000,
    )


def test_engine_video_display_rect_uses_fullscreen_for_unset_geometry(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config_repo = MagicMock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.display_x": 0,
        "viewer.display_y": 0,
        "viewer.display_w": None,
        "viewer.display_h": None,
    }.get(key, default)
    mock_renderer.get_display_rect.return_value = (0, 0, 1800, 1000)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    assert engine._video_display_rect() == (0, 0, 0, 0)
    assert engine._video_frame_dimensions() == (1800, 1000)


def test_engine_video_handoff_uses_fullscreen_for_unset_geometry(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    config_repo = MagicMock()
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.display_x": 0,
        "viewer.display_y": 0,
        "viewer.display_w": None,
        "viewer.display_h": None,
    }.get(key, default)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
        video_player=mock_video_player,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.return_value = media_item
    mock_renderer.get_display_rect.return_value = (0, 0, 1800, 1000)

    with patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=None,
    ):
        engine._trigger_next_media()

    mock_video_player.play.assert_called_once_with(media_item, 0, 0, 0, 0)


def test_engine_video_first_frame_timeout_completes_handoff(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config["video_first_frame_timeout"] = 0.5
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = media_item
    engine._pending_last_img = MagicMock()
    engine._video_first_frame_deadline = 10.0

    engine._handle_video_first_frame_timeout(10.5)

    assert engine._state == State.PLAYING
    assert engine._pending_swap_media == media_item
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_video_first_frame_deadline")


def test_engine_software_fallback_warning_extends_first_frame_deadline(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config["video_software_fallback_first_frame_timeout"] = 8.0
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    media_item = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = media_item
    engine._video_first_frame_deadline = 10.0

    with patch("picframe.core.engine.playback.time.time", return_value=11.0):
        engine._handle_video_playback_warning(
            VideoPlaybackWarningEvent(
                warning_type="software_fallback",
                decoder="avdec_h264",
            )
        )

    assert engine._video_first_frame_deadline == 19.0
    assert engine._state == State.PREPARING_VIDEO


def test_engine_playback_completed_before_first_frame_advances(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    engine._pending_last_img = MagicMock()
    engine._pending_last_frame_path = "/cache/video.2.frame"
    engine._video_first_frame_deadline = 10.0

    from picframe.core.events.dto import PlaybackCompletedEvent, RenderCommand

    with patch("picframe.core.engine.playback.time.time", return_value=100.0):
        engine._handle_playback_completed(PlaybackCompletedEvent())

    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")
    assert engine._video_stop_time == 100.0 + VIDEO_EOS_REDRAW_TIMEOUT_SECONDS
    assert engine._video_stop_frames_remaining == VIDEO_EOS_REDRAW_FRAMES
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_pending_last_img")
    assert not hasattr(engine, "_pending_last_frame_path")
    assert not hasattr(engine, "_video_first_frame_deadline")
    render_cmd = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "RESUME"
    mock_video_player.stop.assert_not_called()

    engine._handle_video_stop_after_eos(100.0 + VIDEO_EOS_REDRAW_TIMEOUT_SECONDS - 0.01)
    mock_video_player.stop.assert_not_called()

    engine._handle_video_stop_after_eos(100.0 + VIDEO_EOS_REDRAW_TIMEOUT_SECONDS)

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")
    assert engine._next_transition_time == 0.0
    assert engine._video_stop_frames_remaining == 0


def test_engine_playback_completed_clears_unexecuted_video_swap_before_next_video(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    monkeypatch,
) -> None:
    """A delayed swap from the previous video must not run during next video prep."""
    mock_video_player = MagicMock()
    mock_renderer.get_display_rect.return_value = (0, 0, 1920, 1080)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    previous_video = MediaItem(
        id=1,
        filepath="/path/to/previous.mp4",
        media_type=MediaType.VIDEO,
        filename="previous.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    next_video = MediaItem(
        id=2,
        filepath="/path/to/next.mp4",
        media_type=MediaType.VIDEO,
        filename="next.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567891.0,
        duration=10.0,
    )
    engine._state = State.PLAYING
    engine._active_video_media = previous_video
    engine._pending_swap_media = previous_video
    engine._pending_swap_last_img = MagicMock()
    engine._pending_swap_last_frame_path = "/cache/previous.2.frame"
    engine._texture_swap_time = 0.0
    timers: list[FakeTimer] = []
    monkeypatch.setattr(
        "picframe.core.engine.playback.threading.Timer",
        lambda interval, callback: timers.append(FakeTimer(interval, callback)) or timers[-1],
    )

    engine._handle_playback_completed(PlaybackCompletedEvent())

    assert not hasattr(engine, "_pending_swap_media")
    assert not hasattr(engine, "_pending_swap_last_img")
    assert not hasattr(engine, "_pending_swap_last_frame_path")
    assert engine._texture_swap_time == float("inf")
    assert not hasattr(engine, "_active_video_media")

    mock_playlist_manager.get_next.return_value = next_video
    mock_renderer.execute.reset_mock()
    with patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=(MagicMock(), MagicMock()),
    ):
        engine._trigger_next_media()

    engine._execute_texture_swap()

    background_swaps = [
        call_args.args[0]
        for call_args in mock_renderer.execute.call_args_list
        if isinstance(call_args.args[0], RenderCommand)
        and call_args.args[0].background_only
    ]
    assert background_swaps == []
    assert engine._state == State.PREPARING_VIDEO
    assert engine._pending_video_media == next_video


def test_engine_playback_completed_refreshes_pi3d_last_frame_before_resume(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    last_img = MagicMock()
    engine._state = State.PLAYING
    engine._active_video_media = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    engine._active_video_last_img = last_img
    engine._active_video_last_frame_path = "/cache/video.2.frame"

    engine._handle_playback_completed(PlaybackCompletedEvent())

    reveal_cmd = mock_renderer.execute.call_args_list[-2].args[0]
    resume_cmd = mock_renderer.execute.call_args_list[-1].args[0]
    assert isinstance(reveal_cmd, RenderCommand)
    assert reveal_cmd.image_path == "/cache/video.2.frame"
    assert reveal_cmd.background_only is True
    assert reveal_cmd.image_obj == last_img
    assert isinstance(resume_cmd, RenderCommand)
    assert resume_cmd.image_path == "RESUME"
    assert not hasattr(engine, "_active_video_media")
    assert not hasattr(engine, "_active_video_last_img")
    assert not hasattr(engine, "_active_video_last_frame_path")
    assert engine._video_stop_frames_remaining == VIDEO_EOS_REDRAW_FRAMES


def test_engine_eos_render_barrier_stops_video_after_required_frames(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    with patch("picframe.core.engine.playback.time.time", return_value=100.0):
        engine._schedule_video_stop_after_eos()

    for _ in range(VIDEO_EOS_REDRAW_FRAMES - 1):
        engine._record_video_eos_redraw_frame()
    mock_video_player.stop.assert_not_called()

    engine._record_video_eos_redraw_frame()

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")
    assert engine._video_stop_frames_remaining == 0
    assert engine._next_transition_time == 0.0


def test_engine_run_loop_waits_for_delayed_video_stop_before_next_media(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._is_running = True
    engine._renderer_started = True
    engine._state = State.PLAYING
    engine._video_stop_time = 100.0
    engine._next_transition_time = float("inf")
    engine._trigger_next_media = MagicMock()
    mock_renderer.render_frame.side_effect = [False]

    with patch("picframe.core.engine.playback.time.time", return_value=99.9):
        engine._run_loop()

    mock_video_player.stop.assert_not_called()
    engine._trigger_next_media.assert_not_called()


def test_engine_run_loop_advances_after_delayed_video_stop(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._is_running = True
    engine._renderer_started = True
    engine._state = State.PLAYING
    engine._video_stop_time = 100.0
    engine._next_transition_time = float("inf")
    engine._trigger_next_media = MagicMock()
    mock_renderer.render_frame.side_effect = [False]

    with patch("picframe.core.engine.playback.time.time", return_value=100.0):
        engine._run_loop()

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")
    assert engine._next_transition_time == 0.0
    engine._trigger_next_media.assert_called_once_with()


def test_engine_run_loop_completes_eos_barrier_after_rendered_frames(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._is_running = True
    engine._renderer_started = True
    engine._state = State.PLAYING
    engine._video_stop_time = 100.0
    engine._video_stop_frames_remaining = VIDEO_EOS_REDRAW_FRAMES
    engine._next_transition_time = float("inf")
    engine._trigger_next_media = MagicMock()
    mock_renderer.render_frame.side_effect = [True] * VIDEO_EOS_REDRAW_FRAMES + [False]

    with patch("picframe.core.engine.playback.time.time", return_value=99.0):
        engine._run_loop()

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")
    assert engine._video_stop_frames_remaining == 0
    engine._trigger_next_media.assert_called_once_with()


def test_engine_trigger_next_media_cancels_pending_video_stop(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    mock_playlist_manager.get_next.return_value = None
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._video_stop_time = 100.0

    engine._trigger_next_media()

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")


def test_engine_stop_cancels_pending_video_stop(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    engine._video_stop_time = 100.0

    engine.stop()

    mock_video_player.stop.assert_called_once_with()
    assert engine._video_stop_time == float("inf")
    assert engine._state == State.IDLE


def test_engine_video_first_frame_handoff_scopes_last_frame_swap(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    video = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    last_img = MagicMock()
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = video
    engine._pending_last_img = last_img
    engine._pending_last_frame_path = "/cache/video.2.frame"
    engine._video_first_frame_deadline = 10.0

    engine._complete_video_first_frame_handoff()

    assert engine._state == State.PLAYING
    assert engine._active_video_media == video
    assert engine._active_video_last_img == last_img
    assert engine._active_video_last_frame_path == "/cache/video.2.frame"
    assert engine._pending_swap_media == video
    assert engine._pending_swap_last_img == last_img
    assert engine._pending_swap_last_frame_path == "/cache/video.2.frame"
    assert engine._texture_swap_time != float("inf")
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_pending_last_img")
    assert not hasattr(engine, "_pending_last_frame_path")
    assert not hasattr(engine, "_video_first_frame_deadline")


def test_engine_stale_video_suspend_timer_is_ignored(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    video = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )
    engine._state = State.PLAYING
    engine._active_video_media = video
    engine._video_suspend_generation = 2

    engine._suspend_renderer_if_video_active(1)
    mock_renderer.execute.assert_not_called()

    engine._suspend_renderer_if_video_active(2)
    render_cmd = mock_renderer.execute.call_args.args[0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "SUSPEND"


def test_engine_circuit_breaker(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Test that the circuit breaker trips after consecutive errors."""
    from picframe.core.exceptions import MediaProcessingError
    
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    engine._is_running = True
    engine._state = State.PLAYING
    engine._renderer_started = True
    
    # Mock renderer to raise MediaProcessingError
    mock_renderer.render_frame.side_effect = MediaProcessingError("Test error")
    
    # Run the loop. It should catch the error, increment the counter, and eventually trip the breaker.
    # We need to patch time.sleep to avoid waiting during the test
    with patch("time.sleep"):
        engine._run_loop()
    
    # The breaker should have tripped after 5 errors
    assert engine._consecutive_errors == 5
    assert engine._state == State.ERROR
    assert engine._is_running is False
    
    # Verify StateEvent(ERROR) was published
    mock_event_publisher.publish.assert_any_call(StateEvent(state=State.ERROR))

def test_playback_engine_handles_media_processing_error(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    playback_engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    """Test that PlaybackEngine catches MediaProcessingError and skips to next media."""
    from picframe.core.events.dto import State, SystemErrorEvent
    from picframe.core.exceptions import MediaProcessingError
    
    # Setup mock to raise MediaProcessingError on render
    mock_renderer.execute.side_effect = MediaProcessingError("Test error")
    
    # Setup playlist manager to return a media item
    media_item = MediaItem(
        id=1, 
        filepath="/path/to/image.jpg",
        filename="image.jpg",
        directory_id=1,
        media_type="image",
        file_size=1024,
        last_modified=1234567890.0
    )
    mock_playlist_manager.get_next.return_value = media_item
    
    # Trigger next media
    playback_engine._trigger_next_media()
    
    # Verify error was handled
    assert playback_engine._consecutive_errors == 1
    mock_event_publisher.publish.assert_any_call(
        SystemErrorEvent(message="Test error", component="PlaybackEngine")
    )
    
    # Verify it skipped to next (transition time set to 0)
    assert playback_engine._next_transition_time == 0.0
    assert playback_engine._state == State.PLAYING
