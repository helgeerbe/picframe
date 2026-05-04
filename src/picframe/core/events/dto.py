"""
Immutable Data Transfer Objects (DTOs) for the Event Bus.

This module defines the core events and commands used for communication
across the application. All events are implemented as frozen dataclasses
to guarantee thread safety when passed between the asynchronous control
loop and the synchronous render loop.
"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class Command(Enum):
    """Enumeration of all possible system commands."""

    NEXT = auto()
    PREV = auto()
    PAUSE = auto()
    PLAY = auto()
    SLEEP = auto()
    WAKE = auto()
    REBOOT_HOST = auto()
    SHUTDOWN_HOST = auto()
    SET_VOL = auto()
    DELETE = auto()
    PURGE_FILES = auto()
    STOP = auto()
    SET_CONFIG = auto()
    TOGGLE_TEXT = auto()
    REFRESH_TEXT = auto()
    DISPLAY_ON = auto()
    DISPLAY_OFF = auto()
    DISPLAY_TOGGLE = auto()
    SET_BRIGHTNESS = auto()
    REQUEST_STATE = auto()


class State(Enum):
    """Enumeration of all possible system states."""

    IDLE = auto()
    PLAYING = auto()
    PAUSED = auto()
    TRANSITIONING = auto()
    SLEEPING = auto()
    CONFIG_CHANGED = auto()
    STATS_UPDATED = auto()


@dataclass(frozen=True)
class Event:
    """
    Base class for all events in the system.

    Provides a default priority property used by the PriorityQueueEventBus
    to determine processing order. Lower values indicate higher priority.
    """

    @property
    def priority(self) -> int:
        """Return the priority of the event (default: 3 - Normal)."""
        return 3


@dataclass(frozen=True)
class CommandEvent(Event):
    """
    An event representing a request for the system to perform an action.

    Attributes:
        command: The specific Command enum value to execute.
        payload: Optional data associated with the command.
    """

    command: Command
    payload: Any = None

    @property
    def priority(self) -> int:
        """
        Determine priority based on the specific command.
        Critical commands (e.g., NEXT, PAUSE, STOP) get high priority (1).
        Standard commands (e.g., SLEEP, SET_VOL) get medium priority (2).
        """
        high_priority = {
            Command.NEXT,
            Command.PREV,
            Command.PAUSE,
            Command.PLAY,
            Command.REBOOT_HOST,
            Command.SHUTDOWN_HOST,
            Command.DELETE,
            Command.STOP,
        }
        return 1 if self.command in high_priority else 2


@dataclass(frozen=True)
class StateEvent(Event):
    """
    An event notifying subscribers that the system's state has changed.

    Attributes:
        state: The specific State enum value representing the new state.
        payload: Optional data associated with the state change.
    """

    state: State
    payload: Any = None

    @property
    def priority(self) -> int:
        """State changes have normal priority (3)."""
        return 3


@dataclass(frozen=True)
class OverlayConfig:
    """
    Configuration for dynamic overlays (text and clock) to be rendered on top of the image.
    """
    show_clock: bool = False
    clock_format: str = "%H:%M"
    show_text: bool = False
    text_string: str = ""


@dataclass(frozen=True)
class RenderCommand(Event):
    """
    An instruction for the Presentation Layer to draw a specific image.

    Attributes:
        image_path: The absolute path to the image file to render.
        overlay: Optional configuration for text overlays.
    """

    image_path: str
    overlay: OverlayConfig | None = None

    @property
    def priority(self) -> int:
        """Render commands have medium priority (2)."""
        return 2


@dataclass(frozen=True)
class FileChangeEvent(Event):
    """
    A notification from the MediaMonitorService that the filesystem changed.

    Attributes:
        event_type: The type of change (e.g., 'created', 'modified').
        path: The absolute path of the file that changed.
    """

    event_type: str
    path: str

    @property
    def priority(self) -> int:
        """File system notifications have low priority (4)."""
        return 4


@dataclass(frozen=True)
class CurrentMediaChangedEvent(Event):
    """
    An event notifying subscribers that the currently displayed media has changed.
    This is the core event for the CQRS metadata broadcasting pattern.

    Attributes:
        media_item: The MediaItem DTO representing the new image/video.
    """

    media_item: Any  # Will be typed as MediaItem once imported/resolved

    @property
    def priority(self) -> int:
        """Metadata broadcasting has normal priority (3)."""
        return 3


@dataclass(frozen=True)
class SystemErrorEvent(Event):
    """
    A notification that a critical error has occurred (Poison Pill).

    Attributes:
        message: A descriptive error message.
        component: The name of the component where the error originated.
    """

    message: str
    component: str

    @property
    def priority(self) -> int:
        """System errors have the highest priority (1)."""
        return 1
