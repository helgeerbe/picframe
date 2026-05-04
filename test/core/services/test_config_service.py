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
    mock_publisher.publish.assert_called_once()
    published_event = mock_publisher.publish.call_args[0][0]
    assert isinstance(published_event, StateEvent)
    assert published_event.state == State.CONFIG_CHANGED
    assert published_event.payload == {"updated_sections": ["viewer"]}
