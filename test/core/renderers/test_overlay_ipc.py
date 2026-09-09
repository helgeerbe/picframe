"""Tests for the overlay IPC protocol (serialization + parsing)."""

import json

from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_DISPLAY_OFF,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_REBOOT_HOST,
    INPUT_ACTION_RESTART_SERVICE,
    INPUT_ACTION_SHUTDOWN_HOST,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    MediaChangedCommand,
    OnScreenPluginsChangedEvent,
    OverlayErrorEvent,
    ReadyEvent,
    ReloadCommand,
    SetConfigCommand,
    SetOpacityCommand,
    ShutdownCommand,
    VisiblePluginsChangedEvent,
    parse_overlay_ipc_message,
)


def test_commands_round_trip_with_type_discriminator() -> None:
    cases = [
        (SetOpacityCommand(opacity=0.5), 0.5),
        (SetConfigCommand(config={"enabled": True}), {"enabled": True}),
        (ReloadCommand(), None),
        (MediaChangedCommand(media={"file_path": "a.jpg", "exif": {}}), None),
        (ShutdownCommand(), None),
    ]
    for cmd, _ in cases:
        data = json.loads(cmd.to_json())
        assert data["type"] in {
            "set_opacity",
            "set_config",
            "reload",
            "media_changed",
            "shutdown",
        }
        again = parse_overlay_ipc_message(cmd.to_json())
        assert isinstance(again, type(cmd))
        assert again == cmd


def test_events_round_trip_with_type_discriminator() -> None:
    cases = [
        ReadyEvent(),
        InputEvent(action=INPUT_ACTION_NEXT),
        OverlayErrorEvent(details="boom", code="webkit_unavailable"),
        OverlayErrorEvent(details="boom"),
        VisiblePluginsChangedEvent(visible_plugins=("clock", "text")),
        VisiblePluginsChangedEvent(visible_plugins=()),
        OnScreenPluginsChangedEvent(on_screen_plugins=("clock", "text")),
        OnScreenPluginsChangedEvent(on_screen_plugins=()),
    ]
    for event in cases:
        again = parse_overlay_ipc_message(event.to_json())
        assert isinstance(again, type(event))
        assert again == event


def test_set_opacity_command_carries_opacity() -> None:
    cmd = parse_overlay_ipc_message(SetOpacityCommand(opacity=0.0).to_json())
    assert isinstance(cmd, SetOpacityCommand)
    assert cmd.opacity == 0.0


def test_set_config_command_carries_config() -> None:
    cmd = parse_overlay_ipc_message(SetConfigCommand(config={"a": 1}).to_json())
    assert isinstance(cmd, SetConfigCommand)
    assert cmd.config == {"a": 1}


def test_media_changed_command_carries_media() -> None:
    payload = {
        "file_path": "x.jpg",
        "media_type": "image",
        "exif": {"title": "T"},
        "location": None,
    }
    cmd = parse_overlay_ipc_message(MediaChangedCommand(media=payload).to_json())
    assert isinstance(cmd, MediaChangedCommand)
    assert cmd.media == payload
    assert cmd.media["file_path"] == "x.jpg"


def test_input_event_action_constants() -> None:
    for action in (
        INPUT_ACTION_PREV,
        INPUT_ACTION_NEXT,
        INPUT_ACTION_TOGGLE,
        INPUT_ACTION_DISPLAY_OFF,
        INPUT_ACTION_RESTART_SERVICE,
        INPUT_ACTION_REBOOT_HOST,
        INPUT_ACTION_SHUTDOWN_HOST,
    ):
        event = parse_overlay_ipc_message(InputEvent(action=action).to_json())
        assert isinstance(event, InputEvent)
        assert event.action == action


def test_parse_returns_none_for_invalid_json() -> None:
    assert parse_overlay_ipc_message("not json") is None


def test_parse_returns_none_for_unknown_type() -> None:
    assert parse_overlay_ipc_message(json.dumps({"type": "bogus"})) is None


def test_parse_returns_none_for_non_object() -> None:
    assert parse_overlay_ipc_message(json.dumps([1, 2, 3])) is None


def test_parse_returns_none_for_missing_required_field() -> None:
    # An InputEvent without an action cannot be constructed.
    assert parse_overlay_ipc_message(json.dumps({"type": "input"})) is None


def test_overlay_error_event_optional_code() -> None:
    event = parse_overlay_ipc_message(OverlayErrorEvent(details="x").to_json())
    assert isinstance(event, OverlayErrorEvent)
    assert event.code is None


def test_visible_plugins_changed_event_carries_list() -> None:
    """The dock-driven visible-plugin change round-trips with its id list (#765)."""
    event = parse_overlay_ipc_message(
        VisiblePluginsChangedEvent(visible_plugins=("clock", "text")).to_json()
    )
    assert isinstance(event, VisiblePluginsChangedEvent)
    assert event.visible_plugins == ("clock", "text")


def test_visible_plugins_changed_event_empty_list() -> None:
    """An empty list (user collapsed every panel) round-trips (#765)."""
    event = parse_overlay_ipc_message(VisiblePluginsChangedEvent(visible_plugins=()).to_json())
    assert isinstance(event, VisiblePluginsChangedEvent)
    assert event.visible_plugins == ()


def test_on_screen_plugins_changed_event_carries_list() -> None:
    """The on-screen (runtime) visibility change round-trips with its id set (#766)."""
    event = parse_overlay_ipc_message(
        OnScreenPluginsChangedEvent(on_screen_plugins=("clock", "text")).to_json()
    )
    assert isinstance(event, OnScreenPluginsChangedEvent)
    assert event.on_screen_plugins == ("clock", "text")


def test_on_screen_plugins_changed_event_coerces_json_list_to_tuple() -> None:
    """``json.loads`` yields a list; the round-tripped event must hold a tuple so
    it equals the original tuple-typed event (#766)."""
    import json

    raw = json.loads(OnScreenPluginsChangedEvent(on_screen_plugins=("clock",)).to_json())
    assert isinstance(raw["on_screen_plugins"], list)  # JSON has no tuple literal
    event = parse_overlay_ipc_message(
        OnScreenPluginsChangedEvent(on_screen_plugins=("clock",)).to_json()
    )
    assert isinstance(event, OnScreenPluginsChangedEvent)
    assert isinstance(event.on_screen_plugins, tuple)
    assert event.on_screen_plugins == ("clock",)


def test_on_screen_plugins_changed_event_empty_list() -> None:
    """An empty on-screen set (every panel auto-hidden) round-trips (#766)."""
    event = parse_overlay_ipc_message(OnScreenPluginsChangedEvent(on_screen_plugins=()).to_json())
    assert isinstance(event, OnScreenPluginsChangedEvent)
    assert event.on_screen_plugins == ()


def test_on_screen_plugins_changed_event_missing_field_defaults_empty() -> None:
    """A malformed payload without ``on_screen_plugins`` parses to an empty tuple
    instead of raising (#766)."""
    import json

    event = parse_overlay_ipc_message(json.dumps({"type": "on_screen_plugins_changed"}))
    assert isinstance(event, OnScreenPluginsChangedEvent)
    assert event.on_screen_plugins == ()
