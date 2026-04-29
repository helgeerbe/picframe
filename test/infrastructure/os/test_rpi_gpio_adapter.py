"""
Tests for the RPiGPIOAdapter.
"""

from unittest.mock import MagicMock, patch

from picframe.infrastructure.os.rpi_gpio_adapter import RPiGPIOAdapter


@patch("picframe.infrastructure.os.rpi_gpio_adapter.Button")
@patch("picframe.infrastructure.os.rpi_gpio_adapter.MotionSensor")
def test_rpi_gpio_adapter_initialization(mock_motion_sensor: MagicMock, mock_button: MagicMock) -> None:
    """Test that the adapter correctly initializes gpiozero devices based on config."""
    config = {
        "btn_next": {"type": "button", "pin": 17, "bounce_time": 0.2},
        "pir_sensor": {"type": "pir", "pin": 27},
    }

    adapter = RPiGPIOAdapter(config)
    adapter.start()

    # Verify Button was created correctly
    mock_button.assert_called_once_with(17, bounce_time=0.2)
    button_instance = mock_button.return_value
    assert hasattr(button_instance, "when_pressed")
    assert hasattr(button_instance, "when_released")

    # Verify MotionSensor was created correctly
    mock_motion_sensor.assert_called_once_with(27)
    pir_instance = mock_motion_sensor.return_value
    assert hasattr(pir_instance, "when_motion")
    assert hasattr(pir_instance, "when_no_motion")

    adapter.stop()
    button_instance.close.assert_called_once()
    pir_instance.close.assert_called_once()


@patch("picframe.infrastructure.os.rpi_gpio_adapter.Button")
def test_rpi_gpio_adapter_callbacks(mock_button: MagicMock) -> None:
    """Test that the adapter correctly invokes the registered callback."""
    config = {
        "btn_next": {"type": "button", "pin": 17},
    }

    adapter = RPiGPIOAdapter(config)
    mock_callback = MagicMock()
    adapter.register_callback(mock_callback)
    adapter.start()

    button_instance = mock_button.return_value

    # Simulate button press
    button_instance.when_pressed()
    mock_callback.assert_called_with("btn_next", "pressed")

    # Simulate button release
    button_instance.when_released()
    mock_callback.assert_called_with("btn_next", "released")

    adapter.stop()
