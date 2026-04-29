"""
Unit tests for the PlaybackEngine.
"""
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.models.media import MediaItem, MediaType


@pytest.fixture
def mock_event_bus() -> MagicMock:
    """Mock the event bus."""
    bus = MagicMock()
    return bus


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
def config() -> dict[str, float]:
    """Default engine configuration."""
    return {
        "time_delay": 10.0,
    }


def test_engine_initialization(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test that the engine initializes correctly."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    
    assert engine._state == State.PAUSED
    assert engine._is_running is False
    assert engine._time_delay == 10.0
    
    # Verify it subscribed to commands
    mock_event_bus.subscribe.assert_called_once_with(CommandEvent, engine._handle_command)


def test_engine_start_stop(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test starting and stopping the engine."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    
    # Mock _run_loop to return immediately so we don't block
    with patch.object(engine, "_run_loop"):
        engine.start()
        
        assert engine._is_running is True
        mock_renderer.start.assert_called_once()
        
        # Should have transitioned to PLAYING
        assert engine._state == State.PLAYING
        
        # Should have published state event
        mock_event_bus.publish.assert_called_with(StateEvent(state=State.PLAYING))
        
        # Should have requested next media
        mock_playlist_manager.get_next.assert_called_once()
        mock_renderer.execute.assert_called_once()
        
        engine.stop()
        
        assert engine._is_running is False
        # renderer.stop() is now called at the end of _run_loop, not in stop()
        assert engine._state == State.PAUSED


def test_engine_handle_command_next(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test handling the NEXT command."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    
    event = CommandEvent(command=Command.NEXT)
    engine._handle_command(event)
    
    mock_playlist_manager.get_next.assert_called_once()
    mock_renderer.execute.assert_called_once()


def test_engine_handle_command_prev(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test handling the PREV command."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    
    event = CommandEvent(command=Command.PREV)
    engine._handle_command(event)
    
    mock_playlist_manager.get_previous.assert_called_once()
    mock_renderer.execute.assert_called_once()


def test_engine_handle_command_pause_play(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test handling PAUSE and PLAY commands."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    
    # Start in PLAYING state
    engine._state = State.PLAYING
    
    # Pause
    event = CommandEvent(command=Command.PAUSE)
    engine._handle_command(event)
    
    assert engine._state == State.PAUSED
    mock_event_bus.publish.assert_called_with(StateEvent(state=State.PAUSED))
    
    # Play
    event = CommandEvent(command=Command.PLAY)
    engine._handle_command(event)
    
    assert engine._state == State.PLAYING
    mock_event_bus.publish.assert_called_with(StateEvent(state=State.PLAYING))


def test_engine_handle_command_stop(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test handling the STOP command."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    engine._is_running = True
    
    event = CommandEvent(command=Command.STOP)
    engine._handle_command(event)
    
    assert engine._is_running is False
    # renderer.stop() is now called at the end of _run_loop, not in stop()
    assert engine._state == State.PAUSED


def test_engine_run_loop_exit(
    mock_event_bus: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, float],
) -> None:
    """Test that the run loop exits when the renderer returns False."""
    engine = PlaybackEngine(
        mock_event_bus, mock_playlist_manager, mock_renderer, config
    )
    engine._is_running = True
    
    # Renderer is mocked to return True then False
    engine._run_loop()
    
    # Should have called render_frame twice
    assert mock_renderer.render_frame.call_count == 2
    
    # Should have stopped the engine
    assert engine._is_running is False
    mock_renderer.stop.assert_called_once()
