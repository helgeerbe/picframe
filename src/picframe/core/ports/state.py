"""
Port interfaces for querying system state.
"""
from enum import Enum
from typing import Any, Protocol


class State(Enum):
    """System states."""
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    PREPARING_VIDEO = "PREPARING_VIDEO"
    ERROR = "ERROR"


class ISystemStateQuery(Protocol):
    """
    Port interface for querying the current state of the system.
    This is used by external delivery mechanisms (MQTT, REST, WebSockets)
    to retrieve the current state without coupling to the core domain.
    """

    def get_current_media(self) -> dict[str, Any] | None:
        """
        Get the currently displayed media item as a dictionary.
        Returns None if no media is currently displayed.
        """
        ...

    def get_system_state(self) -> dict[str, Any]:
        """
        Get the overall system state (e.g., playing, paused, sleeping).
        """
        ...
