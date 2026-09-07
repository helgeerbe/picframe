"""Tests for the overlay IPC protocol (serialization + parsing)."""

import json

from picframe.core.renderers.overlay_ipc import (
    INPUT_ACTION_HIDE,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_PREV,
    INPUT_ACTION_TOGGLE,
    InputEvent,
    OverlayErrorEvent,
    ReadyEvent,
    ReloadCommand,
    SetConfigCommand,
    SetOpacityCommand,
    ShutdownCommand,
    parse_overlay_ipc_message,
)


def test_commands_round_trip_with_type_discriminator() -> None:
    cases = [
        (SetOpacityCommand(opacity=0.5), 0.5),
        (SetConfigCommand(config={"enabled": True}), {"enabled": True}),
        (ReloadCommand(), None),
        (ShutdownCommand(), None),
    ]
    for cmd, _ in cases:
        data = json.loads(cmd.to_json())
        assert data["type"] in {"set_opacity", "set_config", "reload", "shutdown"}
        again = parse_overlay_ipc_message(cmd.to_json())
        assert isinstance(again, type(cmd))
        assert again == cmd


def test_events_round_trip_with_type_discriminator() -> None:
    cases = [
        ReadyEvent(),
        InputEvent(action=INPUT_ACTION_NEXT),
        OverlayErrorEvent(details="boom", code="webkit_unavailable"),
        OverlayErrorEvent(details="boom"),
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


def test_input_event_action_constants() -> None:
    for action in (INPUT_ACTION_PREV, INPUT_ACTION_NEXT, INPUT_ACTION_TOGGLE, INPUT_ACTION_HIDE):
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
