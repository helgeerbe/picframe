from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class Command(Enum):
    NEXT = auto()
    PREV = auto()
    PAUSE = auto()
    PLAY = auto()
    SLEEP = auto()
    WAKE = auto()
    REBOOT = auto()
    SHUTDOWN = auto()
    SET_VOL = auto()
    DELETE = auto()
    PURGE_FILES = auto()
    STOP = auto()
    SET_CONFIG = auto()
    TOGGLE_TEXT = auto()
    REFRESH_TEXT = auto()


class State(Enum):
    PLAYING = auto()
    PAUSED = auto()
    SLEEPING = auto()
    CONFIG_CHANGED = auto()
    STATS_UPDATED = auto()


@dataclass(frozen=True)
class Event:
    """Base class for all events."""

    @property
    def priority(self) -> int:
        return 3  # Default normal priority


@dataclass(frozen=True)
class CommandEvent(Event):
    command: Command
    payload: Any = None

    @property
    def priority(self) -> int:
        high_priority = {
            Command.NEXT,
            Command.PREV,
            Command.PAUSE,
            Command.PLAY,
            Command.REBOOT,
            Command.SHUTDOWN,
            Command.DELETE,
            Command.STOP,
        }
        return 1 if self.command in high_priority else 2


@dataclass(frozen=True)
class StateEvent(Event):
    state: State
    payload: Any = None

    @property
    def priority(self) -> int:
        return 3


@dataclass(frozen=True)
class RenderCommand(Event):
    image_path: str
    overlay: Any = None

    @property
    def priority(self) -> int:
        return 2


@dataclass(frozen=True)
class FileChangeEvent(Event):
    event_type: str
    path: str

    @property
    def priority(self) -> int:
        return 4


@dataclass(frozen=True)
class SystemErrorEvent(Event):
    message: str
    component: str

    @property
    def priority(self) -> int:
        return 1
