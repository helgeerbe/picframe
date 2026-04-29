"""
Tests for the DisplayPowerManager service.
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.services.display_power import DisplayPowerManager


def test_display_power_manager_initialization() -> None:
    """Test that the manager subscribes to the event bus on initialization."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()

    manager = DisplayPowerManager(mock_bus, mock_adapter)

    mock_bus.subscribe.assert_called_once_with(CommandEvent, manager._handle_command_event)


def test_display_power_manager_handles_display_on() -> None:
    """Test that the manager calls turn_on when receiving DISPLAY_ON command."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.DISPLAY_ON)
    manager._handle_command_event(event)

    mock_adapter.turn_on.assert_called_once()
    mock_adapter.turn_off.assert_not_called()
    mock_adapter.toggle.assert_not_called()


def test_display_power_manager_handles_display_off() -> None:
    """Test that the manager calls turn_off when receiving DISPLAY_OFF command."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.DISPLAY_OFF)
    manager._handle_command_event(event)

    mock_adapter.turn_off.assert_called_once()
    mock_adapter.turn_on.assert_not_called()
    mock_adapter.toggle.assert_not_called()


def test_display_power_manager_handles_display_toggle() -> None:
    """Test that the manager calls toggle when receiving DISPLAY_TOGGLE command."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.DISPLAY_TOGGLE)
    manager._handle_command_event(event)

    mock_adapter.toggle.assert_called_once()
    mock_adapter.turn_on.assert_not_called()
    mock_adapter.turn_off.assert_not_called()


def test_display_power_manager_ignores_other_commands() -> None:
    """Test that the manager ignores commands not related to display power."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.NEXT)
    manager._handle_command_event(event)

    mock_adapter.turn_on.assert_not_called()
    mock_adapter.turn_off.assert_not_called()
    mock_adapter.toggle.assert_not_called()


def test_display_power_manager_ignores_non_command_events() -> None:
    """Test that the manager ignores events that are not CommandEvents."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    # Pass a string instead of a CommandEvent
    manager._handle_command_event("Not an event")

    mock_adapter.turn_on.assert_not_called()
    mock_adapter.turn_off.assert_not_called()
    mock_adapter.toggle.assert_not_called()
