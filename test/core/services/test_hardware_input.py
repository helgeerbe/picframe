"""
Tests for the HardwareInputService.
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.services.hardware_input import HardwareInputService
from picframe.infrastructure.os.mock_adapters import MockHardwareInput


def test_hardware_input_service_translates_events() -> None:
    """Test that the service correctly translates hardware events to CommandEvents."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "next_button": {"pressed": "NEXT"},
        "motion_sensor": {"motion_detected": "DISPLAY_ON", "no_motion": "DISPLAY_OFF"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate button press
    mock_adapter.simulate_event("next_button", "pressed")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.NEXT))

    # Simulate motion detected
    mock_adapter.simulate_event("motion_sensor", "motion_detected")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.DISPLAY_ON))

    # Simulate no motion
    mock_adapter.simulate_event("motion_sensor", "no_motion")
    mock_event_bus.publish.assert_called_with(CommandEvent(command=Command.DISPLAY_OFF))

    service.stop()


def test_hardware_input_service_ignores_unmapped_events() -> None:
    """Test that the service ignores events that are not in the mapping."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "next_button": {"pressed": "NEXT"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate unmapped input ID
    mock_adapter.simulate_event("unknown_button", "pressed")
    mock_event_bus.publish.assert_not_called()

    # Simulate unmapped action for a known input ID
    mock_adapter.simulate_event("next_button", "released")
    mock_event_bus.publish.assert_not_called()

    service.stop()


def test_hardware_input_service_handles_invalid_commands() -> None:
    """Test that the service handles invalid command names in the mapping gracefully."""
    mock_event_bus = MagicMock()
    mock_adapter = MockHardwareInput()

    input_mapping = {
        "bad_button": {"pressed": "INVALID_COMMAND_NAME"},
    }

    service = HardwareInputService(mock_event_bus, mock_adapter, input_mapping)
    service.start()

    # Simulate event that maps to an invalid command
    mock_adapter.simulate_event("bad_button", "pressed")
    mock_event_bus.publish.assert_not_called()

    service.stop()
