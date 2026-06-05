from unittest.mock import MagicMock

import pytest

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
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
        "peripherals.buttons.pause": "KEY_P"
    }
    
    config = config_service.get_nested_config()
    
    assert config["viewer"]["fps"] == 60
    assert config["viewer"]["show_clock"] is True
    assert config["peripherals"]["buttons"]["pause"] == "KEY_P"

def test_update_nested_config(config_service, mock_repo):
    nested_config = {
        "viewer": {
            "fps": 30,
            "show_clock": False
        },
        "peripherals": {
            "buttons": {
                "pause": "KEY_SPACE"
            }
        }
    }
    
    config_service.update_nested_config(nested_config)
    
    mock_repo.set_app_config.assert_any_call("viewer.fps", 30)
    mock_repo.set_app_config.assert_any_call("viewer.show_clock", False)
    mock_repo.set_app_config.assert_any_call("peripherals.buttons.pause", "KEY_SPACE")
    assert mock_repo.set_app_config.call_count == 3

def test_handle_set_config_command(config_service, mock_repo, mock_publisher):
    payload = {
        "viewer": {"fps": 60}
    }
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


def test_renderer_config_update_includes_matting_values(
    config_service, mock_repo, mock_publisher
):
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
    mock_repo.get_app_config_bool.side_effect = lambda key, default=False: bool_values.get(key, default)

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
    assert event.config.mat_resource_folder == "~/mat"
