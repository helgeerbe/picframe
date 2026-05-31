"""
Unit tests for the PlaybackEngine.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.models.media import MediaItem, MediaType


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
    
    event = CommandEvent(command=Command.STOP)
    engine._handle_command(event)
    
    assert engine._is_running is False
    # renderer.stop() is now called at the end of _run_loop, not in stop()
    assert engine._state == State.IDLE


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
         patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames", return_value=(MagicMock(), MagicMock())):
        engine._trigger_next_media()
    
    # Verify state changed to PREPARING_VIDEO
    assert engine._state == State.PREPARING_VIDEO
    
    # Verify renderer was sent the first frame
    from picframe.core.events.dto import RenderCommand
    call_args = mock_renderer.execute.call_args[0][0]
    assert isinstance(call_args, RenderCommand)
    assert call_args.image_path == "/path/to/video.1.frame"


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
    from picframe.core.exceptions import MediaProcessingError
    from picframe.core.events.dto import State, SystemErrorEvent
    
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
