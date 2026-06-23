"""
Tests for the DisplayPowerManager service.
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.services.display_power import DisplayPowerManager


def test_display_power_manager_initialization() -> None:
    """Test that the manager subscribes to the event bus on initialization."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()

    manager = DisplayPowerManager(mock_bus, mock_adapter)

    mock_bus.subscribe.assert_any_call(CommandEvent, manager._handle_command_event)
    mock_bus.subscribe.assert_any_call(StateEvent, manager._handle_state_event)


def test_display_power_manager_handles_display_on() -> None:
    """Test that the manager calls turn_on when receiving DISPLAY_ON command."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = False
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.DISPLAY_ON)
    manager._handle_command_event(event)

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_on.assert_called_once()
    mock_adapter.turn_off.assert_not_called()
    mock_adapter.toggle.assert_not_called()


def test_display_power_manager_display_on_publishes_play_when_previously_off() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = False
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_ON))

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_on.assert_called_once()
    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.PLAY))


def test_display_power_manager_display_on_noops_when_already_on() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = True
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_ON))

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_on.assert_not_called()
    mock_publisher.publish.assert_not_called()


def test_display_power_manager_handles_display_off() -> None:
    """Test that the manager calls turn_off when receiving DISPLAY_OFF command."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = True
    manager = DisplayPowerManager(mock_bus, mock_adapter)

    event = CommandEvent(command=Command.DISPLAY_OFF)
    manager._handle_command_event(event)

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_off.assert_called_once()
    mock_adapter.turn_on.assert_not_called()
    mock_adapter.toggle.assert_not_called()


def test_display_power_manager_display_off_publishes_pause_when_previously_on() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = True
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_OFF))

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_off.assert_called_once()
    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.PAUSE))


def test_display_power_manager_display_off_noops_when_already_off() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = False
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_OFF))

    mock_adapter.is_on.assert_called_once()
    mock_adapter.turn_off.assert_not_called()
    mock_publisher.publish.assert_not_called()


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


def test_display_power_manager_display_toggle_publishes_pause_when_final_state_off() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = False
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_TOGGLE))

    mock_adapter.toggle.assert_called_once()
    mock_adapter.is_on.assert_called_once()
    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.PAUSE))


def test_display_power_manager_display_toggle_publishes_play_when_final_state_on() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.is_on.return_value = True
    mock_publisher = MagicMock()
    manager = DisplayPowerManager(
        mock_bus,
        mock_adapter,
        event_publisher=mock_publisher,
    )

    manager._handle_command_event(CommandEvent(command=Command.DISPLAY_TOGGLE))

    mock_adapter.toggle.assert_called_once()
    mock_adapter.is_on.assert_called_once()
    mock_publisher.publish.assert_called_once_with(CommandEvent(command=Command.PLAY))


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


def test_display_power_manager_retargets_display_output_on_viewer_config_change() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    mock_config_repo = MagicMock()
    mock_config_repo.get_app_config.return_value = "HDMI-A-2"
    manager = DisplayPowerManager(mock_bus, mock_adapter, config_repository=mock_config_repo)

    manager._handle_state_event(
        StateEvent(
            state=State.CONFIG_CHANGED,
            payload={"updated_sections": ["viewer"]},
        )
    )

    mock_adapter.set_display_output.assert_called_once_with("HDMI-A-2")
