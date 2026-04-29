"""
Port interfaces for querying system state.
"""
from typing import Any, Dict, Optional, Protocol


class ISystemStateQuery(Protocol):
    """
    Port interface for querying the current state of the system.
    This is used by external delivery mechanisms (MQTT, REST, WebSockets)
    to retrieve the current state without coupling to the core domain.
    """

    def get_current_media(self) -> Optional[Dict[str, Any]]:
        """
        Get the currently displayed media item as a dictionary.
        Returns None if no media is currently displayed.
        """
        ...

    def get_system_state(self) -> Dict[str, Any]:
        """
        Get the overall system state (e.g., playing, paused, sleeping).
        """
        ...
