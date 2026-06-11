from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from picframe.core.engine.playback import PlaybackEngine, VIDEO_EOS_REDRAW_FRAMES
from picframe.core.events.dto import (
    PlaybackCompletedEvent,
    RenderCommand,
    State,
    TransitionCompletedEvent,
    VideoFirstFrameRenderedEvent,
)
from picframe.core.models.media import MediaItem, MediaType


@pytest.fixture
def mock_event_publisher() -> MagicMock:
    return MagicMock()

@pytest.fixture
def mock_event_subscriber() -> MagicMock:
    return MagicMock()

@pytest.fixture
def mock_playlist_manager() -> MagicMock:
    manager = MagicMock()
    # Setup a sequence of media items: Image -> Video -> Image
    image1 = MediaItem(id=1, filepath="/path/to/image1.jpg", filename="image1.jpg", directory_id=1, file_size=100, last_modified=1000, media_type=MediaType.IMAGE)
    video = MediaItem(id=2, filepath="/path/to/video.mp4", filename="video.mp4", directory_id=1, file_size=1000, last_modified=1000, media_type=MediaType.VIDEO)
    video.duration = 10.0
    image2 = MediaItem(id=3, filepath="/path/to/image2.jpg", filename="image2.jpg", directory_id=1, file_size=100, last_modified=1000, media_type=MediaType.IMAGE)
    
    manager.get_next.side_effect = [video, image2]
    manager.get_current.return_value = image1
    return manager

@pytest.fixture
def mock_renderer() -> MagicMock:
    mock = MagicMock()
    mock.get_display_rect.return_value = (0, 0, 1920, 1080)
    return mock

@pytest.fixture
def mock_video_player() -> MagicMock:
    return MagicMock()

@pytest.fixture
def config() -> dict[str, Any]:
    return {
        "time_delay": 2.0,
        "fade_time": 1.0,
        "shuffle": False,
    }

def test_video_handoff_sequence(
    mock_event_publisher: MagicMock,
    mock_event_subscriber: MagicMock,
    mock_playlist_manager: MagicMock,
    mock_renderer: MagicMock,
    mock_video_player: MagicMock,
    config: dict[str, Any],
) -> None:
    """
    Test the full handoff sequence:
    1. Image playing
    2. Next media is Video -> Send .1.frame to renderer, state PREPARING_VIDEO
    3. TransitionCompletedEvent -> Play video, state PLAYING_VIDEO
    4. VideoFirstFrameRenderedEvent -> Swap texture to .2.frame
    5. PlaybackCompletedEvent -> Next media is Image -> Send image to renderer, state PLAYING_IMAGE
    """
    engine = PlaybackEngine(
        event_publisher=mock_event_publisher,
        event_subscriber=mock_event_subscriber,
        playlist_manager=mock_playlist_manager,
        renderer=mock_renderer,
        video_player=mock_video_player,
        config=config,
    )
    
    # 1. Initial state: PLAYING
    engine._change_state(State.PLAYING)
    mock_playlist_manager.get_current.return_value = MediaItem(id=1, filepath="/path/to/image1.jpg", filename="image1.jpg", directory_id=1, file_size=100, last_modified=1000, media_type=MediaType.IMAGE)
    
    # 2. Trigger next media (Video)
    with patch("os.path.exists", return_value=True),          patch("picframe.core.utils.video_frame_extractor.VideoFrameExtractor.get_first_and_last_frames", return_value=(MagicMock(), MagicMock())):
        # Set duration so it passes the duration > 0 check
        # The mock_playlist_manager.get_next has a side_effect, so we need to modify the first item in the side_effect list
        # video_item = mock_playlist_manager.get_next.side_effect[0]
        # video_item.duration = 10.0
        engine._trigger_next_media()
        
    assert engine._state == State.PREPARING_VIDEO
    # _current_media is not updated until the transition completes or we fetch it from playlist manager
    # The pending media is stored in _pending_video_media
    assert engine._pending_video_media.filepath == "/path/to/video.mp4"
    
    # Verify renderer was sent the first frame
    render_call = mock_renderer.execute.call_args[0][0]
    assert isinstance(render_call, RenderCommand)
    assert render_call.image_path == "/path/to/video.1.frame"
    
    # 3. Transition completed for the first frame
    engine._handle_transition_completed(TransitionCompletedEvent())
    
    assert engine._state == State.PREPARING_VIDEO
    mock_video_player.play.assert_called_once_with(engine._pending_video_media, 0, 0, 1920, 1080)
    
    # 4. Video first frame rendered (GStreamer is ready)
    # We need to mock threading.Timer to execute immediately for the test
    with patch("os.path.exists", return_value=True), \
         patch("threading.Timer") as mock_timer:
        
        # Setup the mock timer to immediately call the function
        mock_timer_instance = MagicMock()
        mock_timer.return_value = mock_timer_instance
        def start_timer() -> None:
            # Call the function passed to Timer
            mock_timer.call_args[0][1]()
        mock_timer_instance.start.side_effect = start_timer
        
        # We need to set _pending_video_media again because it was deleted in the previous step
        # Wait, it shouldn't be deleted in _handle_transition_completed. Let's check.
        # Ah, it's deleted in _handle_video_first_frame_rendered.
        # But we need it to be there for _handle_video_first_frame_rendered to work.
        # Let's make sure it's still there.
        engine._pending_video_media = MediaItem(id=2, filepath="/path/to/video.mp4", filename="video.mp4", directory_id=1, file_size=1000, last_modified=1000, media_type=MediaType.VIDEO)
        
        engine._handle_video_first_frame_rendered(VideoFirstFrameRenderedEvent())
        
        # Manually trigger the texture swap that would normally happen in the run loop
        engine._execute_texture_swap()
        
    assert engine._state == State.PLAYING  # type: ignore
    
    # Verify renderer was sent the last frame for background loading
    # The last call is SUSPEND, the one before is the RenderCommand for the swap
    swap_call = mock_renderer.execute.call_args_list[-2][0][0]
    assert isinstance(swap_call, RenderCommand)
    assert swap_call.image_path == "/path/to/video.2.frame"
    assert swap_call.background_only is True
    
    # 5. Video playback completed
    with patch("os.path.exists", return_value=True):
        engine._handle_playback_completed(PlaybackCompletedEvent())

        reveal_call = mock_renderer.execute.call_args_list[-2][0][0]
        resume_call = mock_renderer.execute.call_args_list[-1][0][0]
        assert isinstance(reveal_call, RenderCommand)
        assert reveal_call.image_path == "/path/to/video.2.frame"
        assert reveal_call.background_only is True
        assert isinstance(resume_call, RenderCommand)
        assert resume_call.image_path == "RESUME"
        assert engine._next_transition_time == float("inf")
        for _ in range(VIDEO_EOS_REDRAW_FRAMES):
            engine._record_video_eos_redraw_frame()

    # The EOS render barrier closes the video window, then the run loop advances.
    assert engine._next_transition_time == 0.0
    
    # Simulate the run loop picking it up
    with patch("os.path.exists", return_value=True):
        engine._trigger_next_media()
        
    assert engine._state == State.PLAYING
    assert mock_playlist_manager.get_next.call_count == 2
    
    # Verify renderer was sent the next image
    final_render_call = mock_renderer.execute.call_args[0][0]
    assert isinstance(final_render_call, RenderCommand)
    assert final_render_call.image_path == "/path/to/image2.jpg"
