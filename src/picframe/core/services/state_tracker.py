"""
Service for tracking system state and exposing it via the ISystemStateQuery port.
"""

import logging
from typing import Any, cast

from picframe.core.events.dto import CurrentMediaChangedEvent, State, StateEvent
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.ports.state import ISystemStateQuery

logger = logging.getLogger(__name__)


class StateTrackerService(ISystemStateQuery):
    """
    Subscribes to state and media change events to maintain a current
    snapshot of the system state. Exposes this state via the ISystemStateQuery
    port for external delivery mechanisms (MQTT, REST, WebSockets).
    """

    def __init__(self, event_subscriber: IEventSubscriber) -> None:
        """
        Initialize the StateTrackerService.

        Args:
            event_subscriber: The event bus subscriber interface.
        """
        self._subscriber = event_subscriber
        self._current_media: dict[str, Any] | None = None
        self._system_state: State = State.PLAYING

        # Subscribe to relevant events
        self._subscriber.subscribe(CurrentMediaChangedEvent, self._handle_media_changed)
        self._subscriber.subscribe(StateEvent, self._handle_state_changed)

    def _handle_media_changed(self, event: Any) -> None:
        """Handle CurrentMediaChangedEvent."""
        if isinstance(event, CurrentMediaChangedEvent):
            if hasattr(event.media_item, "to_dict") and callable(event.media_item.to_dict):
                self._current_media = cast(dict[str, Any], event.media_item.to_dict())
            elif hasattr(event.media_item, "__dict__"):
                self._current_media = cast(dict[str, Any], event.media_item.__dict__)
            elif isinstance(event.media_item, dict):
                self._current_media = event.media_item
            else:
                self._current_media = {"raw": str(event.media_item)}
            logger.debug("StateTracker updated current media")

    def _handle_state_changed(self, event: Any) -> None:
        """Handle StateEvent."""
        if isinstance(event, StateEvent):
            self._system_state = event.state
            logger.debug(f"StateTracker updated system state to {self._system_state.name}")

    def get_current_media(self) -> dict[str, Any] | None:
        """
        Get the currently displayed media item as a dictionary.
        Returns None if no media is currently displayed.
        """
        return self._current_media

    def get_system_state(self) -> dict[str, Any]:
        """
        Get the overall system state.
        """
        return {
            "state": self._system_state.name,
            "is_playing": self._system_state == State.PLAYING,
            "is_paused": self._system_state == State.PAUSED,
            "is_sleeping": self._system_state == State.SLEEPING,
        }
