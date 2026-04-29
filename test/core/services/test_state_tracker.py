import pytest
from unittest.mock import Mock

from picframe.core.events.bus import IEventSubscriber
from picframe.core.events.dto import CurrentMediaChangedEvent, State, StateEvent
from picframe.core.services.state_tracker import StateTrackerService


@pytest.fixture
def mock_subscriber() -> Mock:
    return Mock(spec=IEventSubscriber)


@pytest.fixture
def state_tracker(mock_subscriber: Mock) -> StateTrackerService:
    return StateTrackerService(mock_subscriber)


def test_initialization(state_tracker: StateTrackerService, mock_subscriber: Mock) -> None:
    """Test that the service subscribes to the correct events on initialization."""
    assert mock_subscriber.subscribe.call_count == 2
    
    # Check subscriptions
    calls = mock_subscriber.subscribe.call_args_list
    subscribed_events = [call[0][0] for call in calls]
    
    assert CurrentMediaChangedEvent in subscribed_events
    assert StateEvent in subscribed_events
    
    # Check initial state
    assert state_tracker.get_current_media() is None
    
    system_state = state_tracker.get_system_state()
    assert system_state["state"] == "PLAYING"
    assert system_state["is_playing"] is True
    assert system_state["is_paused"] is False
    assert system_state["is_sleeping"] is False


def test_handle_media_changed(state_tracker: StateTrackerService) -> None:
    """Test that the service updates its current media when a CurrentMediaChangedEvent is received."""
    class MockMediaItem:
        def __init__(self):
            self.path = "/path/to/image.jpg"
            self.title = "Test Image"
            
    media_item = MockMediaItem()
    event = CurrentMediaChangedEvent(media_item=media_item)
    
    state_tracker._handle_media_changed(event)
    
    current_media = state_tracker.get_current_media()
    assert current_media is not None
    assert current_media["path"] == "/path/to/image.jpg"
    assert current_media["title"] == "Test Image"


def test_handle_media_changed_dict(state_tracker: StateTrackerService) -> None:
    """Test that the service handles dict media items correctly."""
    media_item = {"path": "/path/to/image.jpg", "title": "Test Image"}
    event = CurrentMediaChangedEvent(media_item=media_item)
    
    state_tracker._handle_media_changed(event)
    
    current_media = state_tracker.get_current_media()
    assert current_media is not None
    assert current_media["path"] == "/path/to/image.jpg"
    assert current_media["title"] == "Test Image"


def test_handle_state_changed(state_tracker: StateTrackerService) -> None:
    """Test that the service updates its system state when a StateEvent is received."""
    event = StateEvent(state=State.PAUSED)
    
    state_tracker._handle_state_changed(event)
    
    system_state = state_tracker.get_system_state()
    assert system_state["state"] == "PAUSED"
    assert system_state["is_playing"] is False
    assert system_state["is_paused"] is True
    assert system_state["is_sleeping"] is False
    
    # Test sleeping state
    event = StateEvent(state=State.SLEEPING)
    state_tracker._handle_state_changed(event)
    
    system_state = state_tracker.get_system_state()
    assert system_state["state"] == "SLEEPING"
    assert system_state["is_playing"] is False
    assert system_state["is_paused"] is False
    assert system_state["is_sleeping"] is True
