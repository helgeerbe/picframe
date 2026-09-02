"""
Unit tests for Event Data Transfer Objects (DTOs).

This module verifies the priority levels assigned to different event types
and ensures that the event objects are immutable to guarantee thread safety.
"""

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
    VideoPlaybackDiagnosticsEvent,
    VideoPlaybackWarningEvent,
)


def test_base_event_priority() -> None:
    """
    Test the default priority of the base Event class.

    Expected behavior:
        The base Event should have a default normal priority of 3.
    """
    event = Event()
    assert event.priority == 3


def test_command_event_priority() -> None:
    """
    Test the priority levels of various CommandEvents.

    Expected behavior:
        Critical commands (e.g., NEXT, PAUSE) should have high priority (1).
        Standard commands (e.g., SET_VOL) should have medium priority (2).
    """
    # High priority commands
    assert CommandEvent(Command.NEXT).priority == 1
    assert CommandEvent(Command.PREV).priority == 1
    assert CommandEvent(Command.PAUSE).priority == 1
    assert CommandEvent(Command.PLAY).priority == 1
    assert CommandEvent(Command.REBOOT_HOST).priority == 1
    assert CommandEvent(Command.SHUTDOWN_HOST).priority == 1
    assert CommandEvent(Command.DELETE).priority == 1
    assert CommandEvent(Command.STOP).priority == 1

    # Medium priority commands
    assert CommandEvent(Command.SET_VOL).priority == 2
    assert CommandEvent(Command.PURGE_FILES).priority == 2
    assert CommandEvent(Command.SET_CONFIG).priority == 2
    assert CommandEvent(Command.TOGGLE_TEXT).priority == 2
    assert CommandEvent(Command.REFRESH_TEXT).priority == 2


def test_legacy_sleep_wake_are_not_commands() -> None:
    """Legacy sleep/wake labels are not part of the active command contract."""
    assert "SLEEP" not in Command.__members__
    assert "WAKE" not in Command.__members__


def test_state_event_priority() -> None:
    """
    Test the priority level of StateEvents.

    Expected behavior:
        All state change notifications should have normal priority (3).
    """
    assert StateEvent(State.PLAYING).priority == 3
    assert StateEvent(State.PAUSED).priority == 3
    assert StateEvent(State.SLEEPING).priority == 3
    assert StateEvent(State.CONFIG_CHANGED).priority == 3
    assert StateEvent(State.STATS_UPDATED).priority == 3


def test_render_command_priority() -> None:
    """
    Test the priority level of RenderCommands.

    Expected behavior:
        Render commands should have medium priority (2) to ensure they are
        processed before normal state events but after critical commands.
    """
    assert RenderCommand("test.jpg").priority == 2


def test_file_change_event_priority() -> None:
    """
    Test the priority level of FileChangeEvents.

    Expected behavior:
        File system notifications should have low priority (4) to avoid
        interrupting playback or user commands.
    """
    assert FileChangeEvent("created", "test.jpg").priority == 4


def test_system_error_event_priority() -> None:
    """
    Test the priority level of SystemErrorEvents.

    Expected behavior:
        System errors should have the highest priority (1) for immediate handling.
    """
    assert SystemErrorEvent("error", "component").priority == 1


def test_video_playback_warning_event_priority() -> None:
    """
    Test the priority level of VideoPlaybackWarningEvents.

    Expected behavior:
        Video playback warnings should be handled before normal state events
        so fallback startup can adjust handoff timing promptly.
    """
    assert VideoPlaybackWarningEvent("software_fallback", "avdec_h264").priority == 2


def test_video_playback_diagnostics_event_priority() -> None:
    """
    Test the priority level of VideoPlaybackDiagnosticsEvents.

    Expected behavior:
        Video playback diagnostics are normal-priority observability events.
    """
    event = VideoPlaybackDiagnosticsEvent(
        pipeline_variant="hardware_direct",
        stage="decoder",
    )
    assert event.priority == 3


def test_event_immutability() -> None:
    """
    Test that Event DTOs are immutable.

    Expected behavior:
        Attempting to modify an attribute of an instantiated event should
        raise an exception (FrozenInstanceError) to ensure thread safety.
    """
    event = CommandEvent(Command.NEXT)
    with pytest.raises(Exception):
        # dataclass frozen=True raises FrozenInstanceError
        event.payload = "test"
