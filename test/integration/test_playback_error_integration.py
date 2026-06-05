import time
from unittest.mock import MagicMock

from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.bus import PriorityQueueEventBus
from picframe.core.events.dto import State, StateEvent, SystemErrorEvent
from picframe.core.exceptions import MediaProcessingError
from picframe.core.models.media import MediaItem, MediaType


def test_playback_media_error_emits_system_error_and_recovers() -> None:
    event_bus = PriorityQueueEventBus()
    observed_errors: list[SystemErrorEvent] = []
    observed_states: list[StateEvent] = []
    event_bus.subscribe(SystemErrorEvent, observed_errors.append)
    event_bus.subscribe(StateEvent, observed_states.append)
    event_bus.start()

    playlist_manager = MagicMock()
    playlist_manager.get_next.return_value = MediaItem(
        id=1,
        filepath="/tmp/image.jpg",
        filename="image.jpg",
        directory_id=1,
        media_type=MediaType.IMAGE,
        file_size=10,
        last_modified=1.0,
    )
    renderer = MagicMock()
    renderer.execute.side_effect = MediaProcessingError("decode failed")

    try:
        engine = PlaybackEngine(
            event_bus,
            event_bus,
            playlist_manager,
            renderer,
            {"time_delay": 10.0, "video_extensions": [".mp4"]},
        )

        engine._trigger_next_media()
        time.sleep(0.1)
    finally:
        event_bus.stop()

    assert engine._consecutive_errors == 1
    assert engine._state == State.PLAYING
    assert len(observed_errors) == 1
    assert observed_errors[0].message == "decode failed"
    assert observed_errors[0].component == "PlaybackEngine"
    assert StateEvent(state=State.PLAYING) in observed_states
