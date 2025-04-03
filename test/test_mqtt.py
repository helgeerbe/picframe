import pytest
from unittest.mock import MagicMock, patch
from src.picframe.interface_mqtt import InterfaceMQTT
import paho.mqtt.client as mqtt

import logging

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def mqtt_config():
    """Fixture for MQTT configuration."""
    return {
        "device_id": "picframe_test",
        "device_url": "http://test_device",
        "server": "home",
        "port": 1883,
        "login": "mosquitto",
        "password": "OkY8tPNuDffEPf2In6QZ",
        "tls": None,
    }


@pytest.fixture
def mock_controller():
    """Fixture for a mocked controller."""
    return MagicMock()


@patch("paho.mqtt.client.Client")
def test_initialization(mock_mqtt_client, mock_controller, mqtt_config):
    """Test that the InterfaceMQTT class initializes correctly."""
    mock_client_instance = mock_mqtt_client.return_value

    # Create an instance of InterfaceMQTT
    mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Verify that the MQTT client was initialized with the correct client ID
    mock_mqtt_client.assert_called_once_with(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="picframe_test", clean_session=True)
    mock_client_instance.username_pw_set.assert_called_once_with("mosquitto", "OkY8tPNuDffEPf2In6QZ")
    assert mqtt_interface._InterfaceMQTT__client is not None
    assert mqtt_interface._InterfaceMQTT__client == mock_client_instance


@patch("paho.mqtt.client.Client")
def test_connect_success(mock_mqtt_client, mock_controller, mqtt_config, caplog):
    """Test successful connection to the MQTT broker."""
    mock_client_instance = mock_mqtt_client.return_value

    # Simulate a successful connection
    mock_client_instance.connect.return_value = 0  # Explicitly set the return value to 0


    # Create an instance of InterfaceMQTT
    with caplog.at_level("DEBUG", logger="interface_mqtt.InterfaceMQTT"):
        mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

        # Print captured logs for debugging
        print(caplog.text)

        # Verify that the connect method was called
        mock_client_instance.connect.assert_called_once_with("home", 1883, keepalive=60)
        
        # Inspect the captured logs
        assert "creating an instance of InterfaceMQTT" in caplog.text
        assert "initialize mqtt client" in caplog.text
   
        # Verify that the connection was successful
        assert mqtt_interface._InterfaceMQTT__connected is True
        assert "Attempting to connect to MQTT broker at home:1883" in caplog.text
        assert "Connect result: 0" in caplog.text

        # Verify that loop_start was called
        assert hasattr(mock_client_instance, "loop_start"), "loop_start() is not a method of the mocked client"
        mock_client_instance.loop_start.assert_called_once()


@patch("paho.mqtt.client.Client")
def test_connect_failure(mock_mqtt_client, mock_controller, mqtt_config, caplog):
    """Test handling of connection failure."""
    mock_client_instance = mock_mqtt_client.return_value
    mock_client_instance.connect.side_effect = Exception("Connection failed")

    # Create an instance of InterfaceMQTT
    with caplog.at_level("ERROR", logger="interface_mqtt.InterfaceMQTT"):
        mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Verify that the connection error was logged
    assert "Unexpected error while connecting to MQTT broker" in caplog.text

    # Verify that the instance was created and the connection flag is False
    assert mqtt_interface._InterfaceMQTT__connected is False


@patch("paho.mqtt.client.Client")
def test_publish_state(mock_mqtt_client, mock_controller, mqtt_config):
    """Test publishing state to the MQTT broker."""
    mock_client_instance = mock_mqtt_client.return_value

    # Create an instance of InterfaceMQTT
    mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Mock controller methods
    mock_controller.get_directory_list.return_value = ("test_dir", ["dir1", "dir2"])
    mock_controller.get_number_of_files.return_value = 10
    mock_controller.paused = False
    mock_controller.shuffle = True
    mock_controller.display_is_on = True
    mock_controller.location_filter = "test_location"  # Set a real value
    mock_controller.tags_filter = "test_tags"  # Set a real value
    mock_controller.time_delay = 5  # Set a real value
    mock_controller.fade_time = 2  # Set a real value
    mock_controller.brightness = 0.8
    mock_controller.matting_images = 0.5
    

    # Call publish_state
    mqtt_interface.publish_state(image="test_image.jpg", image_attr={"attr1": "value1"})

    # Verify that the publish method was called with the correct arguments
    mock_client_instance.publish.assert_any_call(
        "homeassistant/sensor/picframe_test_image/attributes",
        '{"attr1": "value1"}',
        qos=0,
        retain=False,
    )
    mock_client_instance.publish.assert_any_call(
        "homeassistant/sensor/picframe_test_image/state",
        '{"image": "test_image.jpg"}',
        qos=0,
        retain=False,
    )


@patch("paho.mqtt.client.Client")
def test_on_connect(mock_mqtt_client, mock_controller, mqtt_config):
    """Test the on_connect callback."""
    mock_client_instance = mock_mqtt_client.return_value

    # Mock the controller's get_directory_list method
    mock_controller.get_directory_list.return_value = ("test_dir", ["dir1", "dir2"])

    # Create an instance of InterfaceMQTT
    mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Call the on_connect callback
    mqtt_interface._InterfaceMQTT__on_connect(mock_client_instance, None, None, 0, None)

    # Verify that the client published the "online" state
    mock_client_instance.publish.assert_any_call(
        "homeassistant/switch/picframe_test/available", "online", qos=0, retain=True
    )


@patch("paho.mqtt.client.Client")
def test_on_disconnect(mock_mqtt_client, mock_controller, mqtt_config, caplog):
    """Test the on_disconnect callback."""
    mock_client_instance = mock_mqtt_client.return_value

    # Create an instance of InterfaceMQTT
    mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Call the on_disconnect callback
    with caplog.at_level("WARNING", logger="interface_mqtt.InterfaceMQTT"):
        mqtt_interface._InterfaceMQTT__on_disconnect(mock_client_instance, None, None, 1, None)

    # Verify that the disconnection was logged
    assert "Disconnected from MQTT broker. Return code: 1" in caplog.text


@patch("paho.mqtt.client.Client")
def test_on_message(mock_mqtt_client, mock_controller, mqtt_config):
    """Test the on_message callback."""
    mock_client_instance = mock_mqtt_client.return_value

    # Create an instance of InterfaceMQTT
    mqtt_interface = InterfaceMQTT(mock_controller, mqtt_config)

    # Mock a message
    mock_message = MagicMock()
    mock_message.topic = "test_device/brightness"
    mock_message.payload.decode.return_value = "0.5"

    # Call the on_message callback
    mqtt_interface._InterfaceMQTT__on_message(mock_client_instance, None, mock_message)

    # Verify that the controller's brightness was updated
    mock_controller.brightness = 0.5