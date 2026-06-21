"""
Unit tests for the PlaybackEngine.
"""
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.dto import (
    RENDER_PARK_VIDEO_REVEAL,
    RENDER_PRELOAD_VIDEO_REVEAL,
    RENDER_PROMOTE_VIDEO_REVEAL,
    RENDER_VIDEO_FIRST_FRAME,
    RENDER_WAKE_VIDEO_REVEAL,
    Command,
    CommandEvent,
    PlaybackCompletedEvent,
    RenderCommand,
    RendererConfig,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
    SystemErrorEvent,
    TransitionCompletedEvent,
    VideoFirstFrameRenderedEvent,
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
    renderer.requires_restart_for_config.return_value = False
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
    mock_event_subscriber.subscribe.assert_any_call(
        PlaybackCompletedEvent,
        engine._handle_playback_completed,
    )
    mock_event_subscriber.subscribe.assert_any_call(
        TransitionCompletedEvent,
        engine._handle_transition_completed,
    )
    mock_event_subscriber.subscribe.assert_any_call(
        VideoFirstFrameRenderedEvent,
        engine._handle_video_first_frame_rendered,
    )


def test_engine_playback_completed_stops_video_and_advances_immediately(
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

    engine._handle_playback_completed(PlaybackCompletedEvent())

    assert mock_renderer.execute.call_args_list[-1].args[0].image_path == "RESUME"
    mock_video_player.stop.assert_called_once_with()
    assert engine._next_transition_time == 0.0
    assert not hasattr(engine, "_active_video_media")


def test_engine_command_event_dispatches_directly(
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
    engine._state = State.PLAYING
    engine._trigger_next_media = MagicMock()

    engine._handle_command(CommandEvent(command=Command.NEXT))

    engine._trigger_next_media.assert_called_once_with()


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


def test_engine_does_not_restart_renderer_in_process_for_service_restart_geometry(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_renderer.requires_restart_for_config.return_value = True
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
    engine._next_transition_time = float("inf")

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

    mock_renderer.requires_restart_for_config.assert_called_once()
    assert engine._renderer_retry_requested is False
    assert engine._next_transition_time == float("inf")


def test_engine_applies_live_renderer_geometry_update_without_restart(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_renderer.requires_restart_for_config.return_value = False
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        renderer_config=RendererConfig(
            display_x=0,
            display_y=0,
            display_w=1920,
            display_h=1080,
        ),
        video_player=mock_video_player,
    )
    engine._renderer_started = True
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = MagicMock()
    engine._active_video_media = MagicMock()
    engine._active_video_uses_reveal_sandwich = True
    engine._video_reveal_park_pending = True
    engine._next_transition_time = float("inf")

    updated = RendererConfig(
        display_x=100,
        display_y=80,
        display_w=1000,
        display_h=900,
    )
    engine._handle_renderer_config_event(RendererConfigUpdatedEvent(config=updated))

    mock_renderer.requires_restart_for_config.assert_called_once()
    assert engine._renderer_retry_requested is False
    assert engine._renderer_config == updated
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_active_video_media")
    assert not hasattr(engine, "_active_video_uses_reveal_sandwich")
    assert engine._video_reveal_park_pending is False
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == 0.0
    mock_video_player.stop.assert_called_once()


def test_engine_run_loop_restarts_renderer_after_retry_request(
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
    engine._renderer_retry_requested = True
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = MagicMock()
    engine._active_video_media = MagicMock()
    engine._active_video_uses_reveal_sandwich = True
    engine._video_reveal_park_pending = True
    engine._next_transition_time = float("inf")
    mock_renderer.render_frame.side_effect = [True, True, True, False]

    engine._run_loop()

    assert mock_video_player.stop.call_count >= 1
    assert mock_renderer.start.call_count == 1
    assert mock_renderer.stop.call_count == 2
    assert mock_renderer.render_frame.call_count == 4
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_active_video_media")
    assert not hasattr(engine, "_active_video_uses_reveal_sandwich")
    assert engine._state == State.PLAYING
    assert engine._video_reveal_park_pending is False
    mock_playlist_manager.build_playlist.assert_called_once()


def test_engine_does_not_restart_renderer_in_process_for_backend_config_update(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_renderer.requires_restart_for_config.return_value = True
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        renderer_config=RendererConfig(use_sdl2=True, use_glx=False),
    )
    engine._renderer_started = True
    engine._next_transition_time = float("inf")

    engine._handle_renderer_config_event(
        RendererConfigUpdatedEvent(
            config=RendererConfig(use_sdl2=False, use_glx=True)
        )
    )

    mock_renderer.requires_restart_for_config.assert_called_once()
    assert engine._renderer_retry_requested is False
    assert engine._next_transition_time == float("inf")


def test_engine_schedules_fresh_render_for_live_visual_config_change(
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
        renderer_config=RendererConfig(show_clock=True, fit=False),
        video_player=mock_video_player,
    )
    engine._renderer_started = True
    engine._state = State.PLAYING
    engine._next_transition_time = float("inf")

    engine._handle_renderer_config_event(
        RendererConfigUpdatedEvent(config=RendererConfig(show_clock=False, fit=True))
    )

    mock_renderer.requires_restart_for_config.assert_called_once()
    assert engine._renderer_retry_requested is False
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == 0.0
    mock_video_player.stop.assert_called_once()


def test_engine_refreshes_video_decode_ceiling_on_viewer_config_change(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config.return_value = "1920x1080"
    mock_video_player = MagicMock()
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=mock_config_repo,
        video_player=mock_video_player,
    )

    engine._handle_state_event(
        StateEvent(
            state=State.CONFIG_CHANGED,
            payload={"updated_sections": ["viewer"]},
        )
    )

    mock_video_player.set_max_software_decode_resolution.assert_called_once_with(
        "1920x1080"
    )


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
    


def test_engine_handle_command_prev_video_uses_handoff_content_rect(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
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
    mock_playlist_manager.get_previous.return_value = media_item
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )
    metadata = MagicMock()
    metadata.matted = True
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)
    metadata.backdrop_path = "/cache/video.1.frame"
    metadata.with_backdrop_path.return_value = metadata
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = True
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.get_first_and_last_frames.return_value = (
        MagicMock(),
        MagicMock(),
    )
    fake_extractor.last_transition_metadata = metadata

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._handle_command(CommandEvent(command=Command.PREV))

    mock_video_player.play.assert_not_called()
    assert engine._state == State.PREPARING_VIDEO
    first_render_call = mock_renderer.execute.call_args.args[0]
    assert first_render_call.render_action == RENDER_VIDEO_FIRST_FRAME

    engine._handle_transition_completed(TransitionCompletedEvent())

    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )


def test_engine_ignores_stale_video_transition_completion_after_fast_next(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    mock_video_player = MagicMock()
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    first_video = MediaItem(
        id=1,
        filepath="/path/to/first.mp4",
        media_type=MediaType.VIDEO,
        filename="first.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
        duration=10.0,
    )
    second_video = MediaItem(
        id=2,
        filepath="/path/to/second.mp4",
        media_type=MediaType.VIDEO,
        filename="second.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567891.0,
        duration=10.0,
    )
    mock_playlist_manager.get_next.side_effect = [first_video, second_video]
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
    )

    def metadata_for(rect: tuple[int, int, int, int]) -> MagicMock:
        metadata = MagicMock()
        metadata.matted = True
        metadata.backdrop = False
        metadata.frame_size = (1000, 800)
        metadata.coordinate_space = "frame_pixels"
        metadata.content_rect = rect
        return metadata

    def extractor_for(metadata: MagicMock) -> MagicMock:
        extractor = MagicMock()
        extractor.cached_transition_frames_valid.return_value = True
        extractor.get_frame_path.side_effect = lambda role: {
            "first": f"/cache/{metadata.content_rect[0]}.1.frame",
            "last": f"/cache/{metadata.content_rect[0]}.2.frame",
        }[role]
        extractor.get_first_and_last_frames.return_value = (
            MagicMock(),
            MagicMock(),
        )
        extractor.last_transition_metadata = metadata
        return extractor

    first_metadata = metadata_for((100, 50, 640, 360))
    second_metadata = metadata_for((200, 60, 320, 180))

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        side_effect=[
            extractor_for(first_metadata),
            extractor_for(second_metadata),
        ],
    ):
        engine._handle_command(CommandEvent(command=Command.NEXT))
        stale_token = engine._pending_video_transition_token
        engine._handle_command(CommandEvent(command=Command.NEXT))
        current_token = engine._pending_video_transition_token

    assert stale_token != current_token

    engine._handle_transition_completed(
        TransitionCompletedEvent(transition_token=stale_token)
    )
    mock_video_player.play.assert_not_called()
    assert engine._state == State.PREPARING_VIDEO

    engine._handle_transition_completed(
        TransitionCompletedEvent(transition_token=current_token)
    )

    mock_video_player.play.assert_called_once_with(
        second_video,
        210,
        80,
        320,
        180,
        False,
        None,
        content_fit="fill",
    )


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
    
    assert engine._state == State.PAUSED
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PAUSED))
    
    # Play
    event = CommandEvent(command=Command.PLAY)
    engine._handle_command(event)
    
    assert engine._state == State.PLAYING
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PLAYING))


def test_engine_pause_toggles_back_to_playing_for_legacy_shortcuts(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher, mock_event_subscriber, mock_playlist_manager, mock_renderer, config
    )
    engine._state = State.PAUSED

    with patch("picframe.core.engine.playback.time.time", return_value=100.0):
        engine._handle_command(CommandEvent(command=Command.PAUSE))

    assert engine._state == State.PLAYING
    assert engine._next_transition_time == 110.0
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PLAYING))


def test_engine_pause_pauses_active_video(
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
    engine._state = State.PLAYING
    engine._active_video_media = MediaItem(
        id=2,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=2048,
        last_modified=1234567890.0,
    )

    engine._handle_command(CommandEvent(command=Command.PAUSE))

    mock_video_player.pause.assert_called_once()
    assert engine._state == State.PAUSED
    mock_event_publisher.publish.assert_called_with(StateEvent(state=State.PAUSED))


def test_engine_play_resumes_active_video_without_scheduling_timer(
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
    engine._state = State.PAUSED
    engine._next_transition_time = 25.0
    engine._active_video_media = MediaItem(
        id=2,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=2048,
        last_modified=1234567890.0,
    )

    engine._handle_command(CommandEvent(command=Command.PLAY))

    mock_video_player.resume.assert_called_once()
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")
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


def test_engine_formats_overlay_date_with_model_locale(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    config_repo = MagicMock()
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "viewer.show_text_enabled": True,
    }.get(key, default)
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.text_overlay_format": "date",
        "viewer.show_text_fm": "%B %d, %Y",
        "model.locale": "de_DE.utf8",
    }.get(key, default)
    media_item = MediaItem(
        id=1,
        filepath="/path/to/image.jpg",
        media_type=MediaType.IMAGE,
        filename="image.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        exif_datetime=1_710_000_000.0,
    )
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    with patch(
        "picframe.core.engine.playback.format_datetime_for_locale",
        return_value="März 09, 2024",
    ) as format_datetime:
        assert engine._generate_text_string(media_item) == "März 09, 2024"

    format_datetime.assert_called_once()
    _, date_format, locale_value = format_datetime.call_args.args
    assert date_format == "%B %d, %Y"
    assert locale_value == "de_DE.utf8"


def test_engine_enqueues_missing_gps_location_with_model_locale(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    media_repo = MagicMock()
    media_repo.get_location.return_value = None
    mock_playlist_manager._media_repo = media_repo
    config_repo = MagicMock()
    config_repo.get_app_config_bool.side_effect = lambda key, default=False: {
        "viewer.show_text_enabled": True,
    }.get(key, default)
    config_repo.get_app_config.side_effect = lambda key, default=None: {
        "viewer.text_overlay_format": "location",
        "viewer.show_text_fm": "%B %d, %Y",
        "model.locale": "de_DE.utf8",
        "viewer.geo_suppress_list": [],
    }.get(key, default)
    media_item = MediaItem(
        id=1,
        filepath="/path/to/image.jpg",
        media_type=MediaType.IMAGE,
        filename="image.jpg",
        directory_id=1,
        file_size=1024,
        last_modified=1.0,
        latitude=52.5,
        longitude=13.4,
    )
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    assert engine._generate_text_string(media_item) == ""
    media_repo.get_location.assert_called_once_with(52.5, 13.4, language="de")
    media_repo.enqueue_location_lookup.assert_called_once_with(52.5, 13.4, language="de")


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
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        video_player=mock_video_player,
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
    assert call_args.render_action == RENDER_VIDEO_FIRST_FRAME
    assert mock_get_frames.call_args.kwargs["extract_missing"] is True


def test_engine_arms_pending_video_before_first_frame_transition_can_complete(
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

    def complete_first_frame_immediately(command: RenderCommand) -> None:
        if command.render_action == RENDER_VIDEO_FIRST_FRAME:
            engine._handle_transition_completed(TransitionCompletedEvent())

    mock_renderer.execute.side_effect = complete_first_frame_immediately

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=(MagicMock(), MagicMock()),
    ):
        engine._trigger_next_media()

    first_render_call = mock_renderer.execute.call_args_list[0].args[0]
    assert isinstance(first_render_call, RenderCommand)
    assert first_render_call.render_action == RENDER_VIDEO_FIRST_FRAME
    assert engine._state == State.PREPARING_VIDEO
    mock_video_player.play.assert_called_once_with(
        media_item, 0, 0, 1920, 1080, False, None
    )


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
        renderer_config=RendererConfig(background=(0.2, 0.2, 0.3, 1.0)),
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

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames",
        return_value=(MagicMock(), MagicMock()),
    ):
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
        background=(0.2, 0.2, 0.3, 1.0),
        matting_config=RendererConfig(background=(0.2, 0.2, 0.3, 1.0)),
        edge_config=RendererConfig(background=(0.2, 0.2, 0.3, 1.0)),
    )
    call_args = mock_renderer.execute.call_args[0][0]
    assert isinstance(call_args, RenderCommand)
    assert call_args.image_path == expected_path


def test_engine_video_metadata_rect_offsets_from_renderer_display_origin(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = MagicMock()
    metadata.matted = True
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)

    assert engine._video_display_rect_for_metadata(metadata) == (
        110,
        70,
        640,
        360,
    )
    assert engine._video_backdrop_rect_for_metadata(metadata) == (
        10,
        20,
        1000,
        800,
    )


def test_engine_video_handoff_uses_matted_content_rect_and_backdrop(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = MagicMock()
    metadata.matted = True
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)
    metadata.backdrop_path = "/cache/video.1.frame"
    metadata.with_backdrop_path.return_value = metadata
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = True
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.get_first_and_last_frames.return_value = (
        MagicMock(),
        MagicMock(),
    )
    fake_extractor.last_transition_metadata = metadata

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._trigger_next_media()
        engine._handle_transition_completed(TransitionCompletedEvent())

    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )


def test_engine_video_handoff_uses_regenerated_metadata_after_cache_miss(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = MagicMock()
    metadata.matted = True
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)
    metadata.backdrop_path = "/cache/video.1.frame"
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = False
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.last_transition_metadata = None

    def generate_frames(*args: Any, **kwargs: Any) -> tuple[MagicMock, MagicMock]:
        fake_extractor.last_transition_metadata = metadata
        return MagicMock(), MagicMock()

    fake_extractor.get_first_and_last_frames.side_effect = generate_frames

    with patch("os.path.exists", return_value=False), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._trigger_next_media()

    assert engine._state == State.PREPARING_VIDEO
    assert engine._pending_video_transition_metadata is metadata
    fake_extractor.get_first_and_last_frames.assert_called_once()

    engine._handle_transition_completed(TransitionCompletedEvent())

    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )


def test_engine_video_handoff_uses_first_frame_path_for_backdrop_metadata_without_path(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = SimpleNamespace(
        matted=True,
        backdrop=True,
        frame_size=(1000, 800),
        coordinate_space="frame_pixels",
        content_rect=(100, 50, 640, 360),
    )
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = False
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.last_transition_metadata = None

    def generate_frames(*args: Any, **kwargs: Any) -> tuple[MagicMock, MagicMock]:
        fake_extractor.last_transition_metadata = metadata
        return MagicMock(), MagicMock()

    fake_extractor.get_first_and_last_frames.side_effect = generate_frames

    with patch("os.path.exists", return_value=False), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._trigger_next_media()
        engine._handle_transition_completed(TransitionCompletedEvent())

    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )


def test_engine_video_handoff_uses_edge_content_rect_and_backdrop(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = MagicMock()
    metadata.matted = False
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)
    metadata.backdrop_path = "/cache/video.1.frame"
    metadata.with_backdrop_path.return_value = metadata
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = True
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.get_first_and_last_frames.return_value = (
        MagicMock(),
        MagicMock(),
    )
    fake_extractor.last_transition_metadata = metadata

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._trigger_next_media()
        engine._handle_transition_completed(TransitionCompletedEvent())

    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )


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
    mock_video_player.play.assert_called_once_with(
        media_item, 10, 20, 1920, 1080, False, None
    )
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")


def test_engine_direct_video_fallback_uses_cached_content_rect(
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
    mock_renderer.get_display_rect.return_value = (10, 20, 1000, 800)
    metadata = MagicMock()
    metadata.matted = True
    metadata.backdrop = True
    metadata.frame_size = (1000, 800)
    metadata.coordinate_space = "frame_pixels"
    metadata.content_rect = (100, 50, 640, 360)
    metadata.backdrop_path = "/cache/video.1.frame"
    metadata.with_backdrop_path.return_value = metadata
    fake_extractor = MagicMock()
    fake_extractor.cached_transition_frames_valid.return_value = True
    fake_extractor.get_frame_path.side_effect = lambda role: {
        "first": "/cache/video.1.frame",
        "last": "/cache/video.2.frame",
    }[role]
    fake_extractor.get_first_and_last_frames.return_value = None
    fake_extractor.last_transition_metadata = metadata

    with patch("os.path.exists", return_value=True), patch(
        "picframe.core.utils.video_frame_extractor.VideoFrameExtractor",
        return_value=fake_extractor,
    ):
        engine._trigger_next_media()

    from picframe.core.events.dto import RenderCommand

    render_cmd = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "RESUME"
    mock_video_player.play.assert_called_once_with(
        media_item,
        110,
        70,
        640,
        360,
        False,
        None,
        host_backdrop_path="/cache/video.1.frame",
        host_backdrop_rect=(10, 20, 1000, 800),
        content_fit="fill",
    )
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")


def test_engine_passes_renderer_background_to_video_player(
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
        renderer_config=RendererConfig(background=(0.2, 0.2, 0.3, 1.0)),
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

    mock_video_player.play.assert_called_once_with(
        media_item,
        10,
        20,
        1920,
        1080,
        False,
        (0.2, 0.2, 0.3, 1.0),
    )


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
    monkeypatch.setattr(
        "picframe.core.engine.playback.VIDEO_TRANSITION_FRAME_GENERATE_TIMEOUT_SECONDS",
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
    mock_video_player.play.assert_called_once_with(
        media_item, 10, 20, 1920, 1080, False, None
    )
    assert engine._state == State.PLAYING
    assert engine._next_transition_time == float("inf")


def test_engine_missing_video_frames_wait_for_generation_budget(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
    )
    first_frame = tmp_path / "video.1.frame"
    last_frame = tmp_path / "video.2.frame"
    frames = (MagicMock(), MagicMock())
    extractor = MagicMock()
    extractor.get_frame_path.side_effect = lambda role: {
        "first": str(first_frame),
        "last": str(last_frame),
    }[role]

    def generate_frames(*args: Any, **kwargs: Any) -> tuple[MagicMock, MagicMock]:
        time.sleep(0.03)
        return frames

    extractor.get_first_and_last_frames.side_effect = generate_frames
    monkeypatch.setattr(
        "picframe.core.engine.playback.VIDEO_TRANSITION_FRAME_LOAD_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "picframe.core.engine.playback.VIDEO_TRANSITION_FRAME_GENERATE_TIMEOUT_SECONDS",
        0.2,
    )

    result = engine._load_video_transition_frames_with_deadline(
        extractor,
        10.0,
        960,
        540,
    )

    assert result == frames
    extractor.get_first_and_last_frames.assert_called_once_with(
        10.0,
        960,
        540,
        extract_missing=True,
    )


def test_engine_video_display_rect_prefers_renderer_actual_custom_rect(
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
    config_repo.get_app_config_bool.return_value = False
    mock_renderer.get_display_rect.return_value = (0, 80, 1800, 1000)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    assert engine._video_display_rect() == (0, 80, 1800, 1000)
    assert engine._video_frame_dimensions() == (1800, 1000)


def test_engine_video_handoff_uses_renderer_actual_custom_rect(
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
    config_repo.get_app_config_bool.return_value = False
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
        0,
        80,
        1800,
        1000,
        False,
        None,
    )


def test_engine_video_display_rect_falls_back_to_configured_custom_rect(
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
    config_repo.get_app_config_bool.return_value = False
    mock_renderer.get_display_rect.return_value = (0, 0, 0, 0)
    engine = PlaybackEngine(
        mock_event_publisher,
        mock_event_subscriber,
        mock_playlist_manager,
        mock_renderer,
        config,
        config_repository=config_repo,
    )

    assert engine._video_display_rect() == (100, 80, 1800, 1000)
    assert engine._video_frame_dimensions() == (1800, 1000)


def test_engine_video_display_rect_uses_fullscreen_sentinel_for_unset_geometry(
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
    config_repo.get_app_config_bool.return_value = False
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
    config_repo.get_app_config_bool.return_value = False
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

    mock_video_player.play.assert_called_once_with(
        media_item, 0, 0, 0, 0, False, None
    )


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
    assert engine._active_video_media == media_item
    assert not hasattr(engine, "_pending_swap_media")
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


def test_engine_transition_completed_preloads_last_frame_before_video_play(
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
    last_img = MagicMock()
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = media_item
    engine._pending_last_img = last_img
    engine._pending_last_frame_path = "/cache/video.2.frame"
    mock_renderer.get_display_rect.return_value = (0, 0, 1920, 1080)

    order: list[str] = []
    mock_renderer.execute.side_effect = lambda _command: order.append("preload")
    mock_video_player.play.side_effect = lambda *_args: order.append("play")

    engine._handle_transition_completed(TransitionCompletedEvent())

    assert order == ["preload", "play"]
    preload_cmd = mock_renderer.execute.call_args.args[0]
    assert isinstance(preload_cmd, RenderCommand)
    assert preload_cmd.image_path == "/cache/video.2.frame"
    assert preload_cmd.image_obj == last_img
    assert preload_cmd.render_action == RENDER_PRELOAD_VIDEO_REVEAL
    mock_video_player.play.assert_called_once_with(
        media_item, 0, 0, 1920, 1080, False, None
    )


def test_engine_first_frame_rendered_promotes_preloaded_last_frame(
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
    engine._state = State.PREPARING_VIDEO
    engine._pending_video_media = video
    engine._pending_last_frame_path = "/cache/video.2.frame"

    engine._complete_video_first_frame_handoff()

    promote_cmd = mock_renderer.execute.call_args.args[0]
    assert isinstance(promote_cmd, RenderCommand)
    assert promote_cmd.image_path == "/cache/video.2.frame"
    assert promote_cmd.render_action == RENDER_PROMOTE_VIDEO_REVEAL
    assert engine._state == State.PLAYING
    assert engine._active_video_uses_reveal_sandwich is True
    assert engine._video_reveal_park_pending is True


def test_engine_parks_video_reveal_after_settle_frames(
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
    engine._start_video_reveal_parking()

    for _ in range(5):
        engine._update_video_reveal_parking(time.time())

    park_cmd = mock_renderer.execute.call_args.args[0]
    assert isinstance(park_cmd, RenderCommand)
    assert park_cmd.render_action == RENDER_PARK_VIDEO_REVEAL
    assert engine._video_reveal_park_pending is False


@patch("time.sleep")
def test_engine_playback_completed_for_sandwich_video_wakes_renderer_before_stop(
    mock_sleep: MagicMock,
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
    engine._state = State.PLAYING
    engine._video_reveal_park_pending = True
    engine._active_video_uses_reveal_sandwich = True
    engine._active_video_media = MediaItem(
        id=1,
        filepath="/path/to/video.mp4",
        media_type=MediaType.VIDEO,
        filename="video.mp4",
        directory_id=1,
        file_size=1024,
        last_modified=1234567890.0,
    )

    engine._handle_playback_completed(PlaybackCompletedEvent())

    wake_cmd = mock_renderer.execute.call_args.args[0]
    assert isinstance(wake_cmd, RenderCommand)
    assert wake_cmd.image_path == "WAKE_VIDEO_REVEAL"
    assert wake_cmd.render_action == RENDER_WAKE_VIDEO_REVEAL
    mock_sleep.assert_called_once_with(0.25)
    mock_video_player.stop.assert_called_once_with()
    assert engine._next_transition_time == 0.0
    assert engine._video_reveal_park_pending is False
    assert not hasattr(engine, "_active_video_media")
    assert not hasattr(engine, "_active_video_uses_reveal_sandwich")


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

    engine._handle_playback_completed(PlaybackCompletedEvent())

    assert engine._state == State.PLAYING
    assert engine._next_transition_time == 0.0
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_pending_last_img")
    assert not hasattr(engine, "_pending_last_frame_path")
    assert not hasattr(engine, "_video_first_frame_deadline")
    render_cmd = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_cmd, RenderCommand)
    assert render_cmd.image_path == "RESUME"
    assert render_cmd.render_action is None
    mock_video_player.stop.assert_called_once_with()


def test_engine_playback_completed_does_not_run_hidden_video_texture_swap(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    config: dict[str, Any],
) -> None:
    """Rollback path avoids hidden pi3d texture uploads while video covers pi3d."""
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
    engine._state = State.PLAYING
    engine._active_video_media = previous_video

    engine._handle_playback_completed(PlaybackCompletedEvent())

    background_swaps = [
        call_args.args[0]
        for call_args in mock_renderer.execute.call_args_list
        if isinstance(call_args.args[0], RenderCommand)
        and call_args.args[0].background_only
    ]
    assert background_swaps == []
    assert not hasattr(engine, "_active_video_media")
    mock_video_player.stop.assert_called_once_with()


def test_engine_playback_completed_resumes_without_last_frame_refresh(
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

    assert len(mock_renderer.execute.call_args_list) == 1
    resume_cmd = mock_renderer.execute.call_args_list[-1].args[0]
    assert isinstance(resume_cmd, RenderCommand)
    assert resume_cmd.image_path == "RESUME"
    assert resume_cmd.render_action is None
    assert not hasattr(engine, "_active_video_media")
    mock_video_player.stop.assert_called_once_with()
    assert engine._next_transition_time == 0.0


def test_engine_stop_stops_active_video(
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

    engine.stop()

    mock_video_player.stop.assert_called_once_with()
    assert engine._state == State.IDLE


def test_engine_video_first_frame_handoff_does_not_schedule_hidden_swap(
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
    assert not hasattr(engine, "_pending_swap_media")
    assert not hasattr(engine, "_pending_swap_last_img")
    assert not hasattr(engine, "_pending_swap_last_frame_path")
    assert not hasattr(engine, "_pending_video_media")
    assert not hasattr(engine, "_pending_last_img")
    assert not hasattr(engine, "_pending_last_frame_path")
    assert not hasattr(engine, "_video_first_frame_deadline")


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
    
    # The loop should catch the error and eventually trip the breaker.
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
