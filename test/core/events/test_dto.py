import pytest

from picframe.core.events import (
    Command,
    CommandEvent,
    Event,
    FileChangeEvent,
    RenderCommand,
    State,
    StateEvent,
    SystemErrorEvent,
)


def test_base_event_priority() -> None:
    event = Event()
    assert event.priority == 3


def test_command_event_priority() -> None:
    # High priority commands
    assert CommandEvent(Command.NEXT).priority == 1
    assert CommandEvent(Command.PREV).priority == 1
    assert CommandEvent(Command.PAUSE).priority == 1
    assert CommandEvent(Command.PLAY).priority == 1
    assert CommandEvent(Command.REBOOT).priority == 1
    assert CommandEvent(Command.SHUTDOWN).priority == 1
    assert CommandEvent(Command.DELETE).priority == 1
    assert CommandEvent(Command.STOP).priority == 1

    # Medium priority commands
    assert CommandEvent(Command.SLEEP).priority == 2
    assert CommandEvent(Command.WAKE).priority == 2
    assert CommandEvent(Command.SET_VOL).priority == 2
    assert CommandEvent(Command.PURGE_FILES).priority == 2
    assert CommandEvent(Command.SET_CONFIG).priority == 2
    assert CommandEvent(Command.TOGGLE_TEXT).priority == 2
    assert CommandEvent(Command.REFRESH_TEXT).priority == 2


def test_state_event_priority() -> None:
    assert StateEvent(State.PLAYING).priority == 3
    assert StateEvent(State.PAUSED).priority == 3
    assert StateEvent(State.SLEEPING).priority == 3
    assert StateEvent(State.CONFIG_CHANGED).priority == 3
    assert StateEvent(State.STATS_UPDATED).priority == 3


def test_render_command_priority() -> None:
    assert RenderCommand("test.jpg").priority == 2


def test_file_change_event_priority() -> None:
    assert FileChangeEvent("created", "test.jpg").priority == 4


def test_system_error_event_priority() -> None:
    assert SystemErrorEvent("error", "component").priority == 1


def test_event_immutability() -> None:
    event = CommandEvent(Command.NEXT)
    with pytest.raises(Exception):
        # dataclass frozen=True raises FrozenInstanceError
        event.payload = "test"
