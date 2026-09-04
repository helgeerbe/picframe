import os
from unittest.mock import MagicMock

import pytest

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.models.hardware_input import hardware_inputs_from_flat_config
from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
from picframe.core.services.config_service import ConfigService


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_subscriber():
    return MagicMock()


@pytest.fixture
def mock_publisher():
    return MagicMock()


@pytest.fixture
def config_service(mock_repo, mock_subscriber, mock_publisher):
    return ConfigService(mock_repo, mock_subscriber, mock_publisher)


def test_get_nested_config(config_service, mock_repo):
    mock_repo.get_all_app_config.return_value = {
        "viewer.fps": 60,
        "viewer.show_clock": True,
        "http.command_debounce_ms": 200,
    }

    config = config_service.get_nested_config()

    assert config["viewer"]["fps"] == 60
    assert config["viewer"]["show_clock"] is True
    assert config["http"]["command_debounce_ms"] == 200


def test_update_nested_config(config_service, mock_repo):
    nested_config = {
        "viewer": {"fps": 30, "show_clock": False},
        "http": {"command_debounce_ms": 250},
    }

    config_service.update_nested_config(nested_config)

    mock_repo.set_app_config.assert_any_call("viewer.fps", 30)
    mock_repo.set_app_config.assert_any_call("viewer.show_clock", False)
    mock_repo.set_app_config.assert_any_call("http.command_debounce_ms", 250)
    assert mock_repo.set_app_config.call_count == 3


def test_update_nested_config_rejects_invalid_hardware_inputs(config_service, mock_repo):
    nested_config = {
        "hardware_inputs": {
            "enabled": True,
            "inputs": {
                "a": {"type": "button", "pin": 17, "actions": {"pressed": "NEXT"}},
                "b": {"type": "pir", "pin": 17, "actions": {"motion_detected": "DISPLAY_ON"}},
            },
        }
    }

    with pytest.raises(ValueError, match="duplicate pin"):
        config_service.update_nested_config(nested_config)

    mock_repo.set_app_config.assert_not_called()


def test_update_nested_config_replaces_stale_hardware_input_flat_keys():
    repo = SQLiteConfigRepository(":memory:")
    try:
        repo.set_app_config("hardware_inputs.enabled", True)
        repo.set_app_config("hardware_inputs.inputs.input_1.type", "pir")
        repo.set_app_config("hardware_inputs.inputs.input_1.pin", 17)
        repo.set_app_config("hardware_inputs.inputs.input_1.no_motion_delay_seconds", 60)
        repo.set_app_config("hardware_inputs.inputs.input_1.actions.motion_detected", "DISPLAY_ON")
        repo.set_app_config("hardware_inputs.inputs.input_1.actions.no_motion", "DISPLAY_OFF")

        service = ConfigService(repo, MagicMock(), MagicMock())
        service.update_nested_config(
            {
                "hardware_inputs": {
                    "enabled": True,
                    "inputs": {
                        "input_1": {
                            "type": "button",
                            "pin": 17,
                            "actions": {"pressed": "NEXT"},
                        }
                    },
                }
            }
        )

        all_config = repo.get_all_app_config()
        assert "hardware_inputs.inputs.input_1.actions.motion_detected" not in all_config
        assert "hardware_inputs.inputs.input_1.actions.no_motion" not in all_config
        assert "hardware_inputs.inputs.input_1.no_motion_delay_seconds" not in all_config
        assert all_config["hardware_inputs.inputs.input_1.actions.pressed"] == "NEXT"
        assert hardware_inputs_from_flat_config(all_config)["inputs"]["input_1"] == {
            "label": "input_1",
            "type": "button",
            "pin": 17,
            "actions": {"pressed": "NEXT"},
            "bounce_time": 0.1,
        }
    finally:
        repo.close()


def test_handle_set_config_command(config_service, mock_repo, mock_publisher):
    payload = {"viewer": {"fps": 60}}
    event = CommandEvent(command=Command.SET_CONFIG, payload=payload)

    config_service._handle_command_event(event)

    mock_repo.set_app_config.assert_called_once_with("viewer.fps", 60)
    assert mock_publisher.publish.call_count == 2

    # First call should be StateEvent
    state_event = mock_publisher.publish.call_args_list[0][0][0]
    assert isinstance(state_event, StateEvent)
    assert state_event.state == State.CONFIG_CHANGED
    assert state_event.payload == {"updated_sections": ["viewer"]}

    # Second call should be RendererConfigUpdatedEvent
    renderer_event = mock_publisher.publish.call_args_list[1][0][0]
    from picframe.core.events.dto import RendererConfigUpdatedEvent

    assert isinstance(renderer_event, RendererConfigUpdatedEvent)


def test_handle_model_timing_config_publishes_renderer_update(
    config_service, mock_repo, mock_publisher
):
    mock_repo.get_app_config.side_effect = lambda key, default=None: {
        "model.fade_time": 3.0,
        "model.time_delay": 30.0,
    }.get(key, default)
    mock_repo.get_app_config_bool.return_value = False
    event = CommandEvent(
        command=Command.SET_CONFIG,
        payload={"model": {"time_delay": 30.0, "fade_time": 3.0}},
    )

    config_service._handle_command_event(event)

    assert mock_publisher.publish.call_count == 2
    from picframe.core.events.dto import RendererConfigUpdatedEvent

    assert isinstance(mock_publisher.publish.call_args_list[1][0][0], RendererConfigUpdatedEvent)


def test_renderer_config_update_includes_matting_values(config_service, mock_repo, mock_publisher):
    values = {
        "viewer.mat_images": "on",
        "viewer.mat_type": "double_flat",
        "viewer.outer_mat_color": [1, 2, 3],
        "viewer.inner_mat_color": "4,5,6",
        "viewer.outer_mat_border": 44,
        "viewer.inner_mat_border": 24,
        "viewer.mat_resource_folder": "~/mat",
    }
    bool_values = {
        "viewer.outer_mat_use_texture": False,
        "viewer.inner_mat_use_texture": True,
    }
    mock_repo.get_app_config.side_effect = lambda key, default=None: values.get(key, default)
    mock_repo.get_app_config_bool.side_effect = lambda key, default=False: bool_values.get(
        key, default
    )

    config_service._publish_renderer_config()

    from picframe.core.events.dto import RendererConfigUpdatedEvent

    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, RendererConfigUpdatedEvent)
    assert event.config.mat_images == "on"
    assert event.config.mat_type == "double_flat"
    assert event.config.outer_mat_color == [1, 2, 3]
    assert event.config.inner_mat_color == "4,5,6"
    assert event.config.outer_mat_border == 44
    assert event.config.inner_mat_border == 24
    assert event.config.outer_mat_use_texture is False
    assert event.config.inner_mat_use_texture is True
    assert event.config.mat_resource_folder == os.path.expanduser("~/mat")


def test_get_nested_config_includes_overlay_section(config_service, mock_repo):
    mock_repo.get_all_app_config.return_value = {
        "overlay.enabled": True,
        "overlay.display_mode": "persistent",
        "overlay.enabled_plugins": ["clock"],
        "overlay.plugin_config.weather.api_key": "secret",
    }

    config = config_service.get_nested_config()

    overlay = config["overlay"]
    assert overlay["enabled"] is True
    assert overlay["display_mode"] == "persistent"
    assert overlay["enabled_plugins"] == ["clock"]
    assert overlay["plugin_config"]["weather"]["api_key"] == "secret"


def test_update_nested_config_persists_overlay(config_service, mock_repo):
    nested_config = {
        "overlay": {
            "enabled": True,
            "display_mode": "persistent",
            "enabled_plugins": ["clock"],
            "plugin_config": {"weather": {"api_key": "secret"}},
        }
    }

    config_service.update_nested_config(nested_config)

    mock_repo.set_app_config.assert_any_call("overlay.enabled", True)
    mock_repo.set_app_config.assert_any_call("overlay.display_mode", "persistent")
    mock_repo.set_app_config.assert_any_call("overlay.enabled_plugins", ["clock"])
    mock_repo.set_app_config.assert_any_call("overlay.plugin_config.weather.api_key", "secret")
    # overlay must NOT trigger a blanket delete-prefix (unlike hardware_inputs)
    mock_repo.delete_app_config_prefix.assert_not_called()


def test_update_plugin_config_scoped_delete_and_write():
    repo = SQLiteConfigRepository(":memory:")
    try:
        repo.set_app_config("overlay.enabled", True)
        repo.set_app_config("overlay.plugin_config.weather.api_key", "old-key")
        repo.set_app_config("overlay.plugin_config.weather.units", "imperial")
        repo.set_app_config("overlay.plugin_config.clock.format", "%H:%M")

        service = ConfigService(repo, MagicMock(), MagicMock())
        service.update_plugin_config("weather", {"api_key": "new-key"})

        all_config = repo.get_all_app_config()
        assert all_config["overlay.plugin_config.weather.api_key"] == "new-key"
        # stale units key removed by scoped delete
        assert "overlay.plugin_config.weather.units" not in all_config
        # other plugins untouched
        assert all_config["overlay.plugin_config.clock.format"] == "%H:%M"
        # rest of overlay untouched
        assert all_config["overlay.enabled"] is True
    finally:
        repo.close()


def test_handle_set_config_overlay_publishes_overlay_config_changed_event(
    config_service, mock_repo, mock_publisher
):
    mock_repo.get_all_app_config.return_value = {
        "overlay.enabled": True,
        "overlay.display_mode": "persistent",
    }
    event = CommandEvent(
        command=Command.SET_CONFIG,
        payload={"overlay": {"display_mode": "persistent"}},
    )

    config_service._handle_command_event(event)

    from picframe.core.events.dto import OverlayConfigChangedEvent

    published = [call.args[0] for call in mock_publisher.publish.call_args_list]
    overlay_events = [e for e in published if isinstance(e, OverlayConfigChangedEvent)]
    assert len(overlay_events) == 1
    overlay_event = overlay_events[0]
    assert overlay_event.overlay_config["display_mode"] == "persistent"
    assert overlay_event.overlay_config["enabled"] is True
    assert overlay_event.updated_plugin_id is None


def test_handle_set_config_plugin_config_reports_updated_plugin_id(
    config_service, mock_repo, mock_publisher
):
    mock_repo.get_all_app_config.return_value = {}
    event = CommandEvent(
        command=Command.SET_CONFIG,
        payload={"overlay": {"plugin_config": {"weather": {"api_key": "k"}}}},
    )

    config_service._handle_command_event(event)

    from picframe.core.events.dto import OverlayConfigChangedEvent

    published = [call.args[0] for call in mock_publisher.publish.call_args_list]
    overlay_event = next(e for e in published if isinstance(e, OverlayConfigChangedEvent))
    assert overlay_event.updated_plugin_id == "weather"


def test_get_nested_config_normalizes_legacy_overlay(config_service, mock_repo):
    """get_nested_config bridges legacy visible_plugin <-> visible_plugins (#752)."""
    mock_repo.get_all_app_config.return_value = {
        "overlay.visible_plugin": "clock",
        "overlay.display_mode": "auto_hide",
    }

    config = config_service.get_nested_config()

    overlay = config["overlay"]
    assert overlay["visible_plugins"] == ["clock"]
    # legacy key re-derived for worker/shell compatibility
    assert overlay["visible_plugin"] == "clock"
    assert overlay["display_mode"] == "auto_hide"


def test_get_nested_config_normalizes_null_visible_plugin(config_service, mock_repo):
    mock_repo.get_all_app_config.return_value = {"overlay.visible_plugin": None}

    config = config_service.get_nested_config()
    assert config["overlay"]["visible_plugins"] == []
    assert config["overlay"]["visible_plugin"] is None


def test_update_plugin_layout_scoped_delete_and_write():
    repo = SQLiteConfigRepository(":memory:")
    try:
        repo.set_app_config("overlay.enabled", True)
        repo.set_app_config("overlay.plugin_layout.weather.position", "top-left")
        repo.set_app_config("overlay.plugin_layout.weather.z_order", 2)
        repo.set_app_config("overlay.plugin_layout.clock.position", "bottom-right")

        service = ConfigService(repo, MagicMock(), MagicMock())
        service.update_plugin_layout("weather", {"position": "top-right", "z_order": 5})

        all_config = repo.get_all_app_config()
        assert all_config["overlay.plugin_layout.weather.position"] == "top-right"
        assert all_config["overlay.plugin_layout.weather.z_order"] == 5
        # other plugins untouched
        assert all_config["overlay.plugin_layout.clock.position"] == "bottom-right"
        # rest of overlay untouched
        assert all_config["overlay.enabled"] is True
    finally:
        repo.close()


def test_update_plugin_layout_skips_none_values():
    repo = SQLiteConfigRepository(":memory:")
    try:
        service = ConfigService(repo, MagicMock(), MagicMock())
        service.update_plugin_layout(
            "weather",
            {"position": "top-right", "width": None, "idle_hide_seconds": 10.0},
        )

        all_config = repo.get_all_app_config()
        assert all_config["overlay.plugin_layout.weather.position"] == "top-right"
        assert all_config["overlay.plugin_layout.weather.idle_hide_seconds"] == 10.0
        # None (inherit/default) keys are not stored
        assert "overlay.plugin_layout.weather.width" not in all_config
    finally:
        repo.close()


def test_handle_set_config_plugin_layout_reports_updated_plugin_id(
    config_service, mock_repo, mock_publisher
):
    """A single-plugin plugin_layout write reports updated_plugin_id (#752)."""
    mock_repo.get_all_app_config.return_value = {}
    event = CommandEvent(
        command=Command.SET_CONFIG,
        payload={"overlay": {"plugin_layout": {"weather": {"position": "top-right"}}}},
    )

    config_service._handle_command_event(event)

    from picframe.core.events.dto import OverlayConfigChangedEvent

    published = [call.args[0] for call in mock_publisher.publish.call_args_list]
    overlay_event = next(e for e in published if isinstance(e, OverlayConfigChangedEvent))
    assert overlay_event.updated_plugin_id == "weather"
