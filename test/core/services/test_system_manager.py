"""Tests for the SystemManager service (#763).

Covers reboot / shutdown / restart-service command handling. The manager
subscribes to ``CommandEvent`` on the event bus and delegates to the injected
``ISystemManager`` HAL adapter.
"""

from unittest.mock import MagicMock

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.services.system_manager import SystemManager


def test_system_manager_initialization() -> None:
    """The manager subscribes to CommandEvent on init."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()

    manager = SystemManager(mock_bus, mock_adapter)

    mock_bus.subscribe.assert_any_call(CommandEvent, manager._handle_command_event)


def test_system_manager_handles_reboot_host() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = SystemManager(mock_bus, mock_adapter)

    manager._handle_command_event(CommandEvent(command=Command.REBOOT_HOST))

    mock_adapter.reboot.assert_called_once()
    mock_adapter.shutdown.assert_not_called()
    mock_adapter.restart_picframe_service.assert_not_called()


def test_system_manager_handles_shutdown_host() -> None:
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = SystemManager(mock_bus, mock_adapter)

    manager._handle_command_event(CommandEvent(command=Command.SHUTDOWN_HOST))

    mock_adapter.shutdown.assert_called_once()
    mock_adapter.reboot.assert_not_called()
    mock_adapter.restart_picframe_service.assert_not_called()


def test_system_manager_handles_restart_service() -> None:
    """RESTART_SERVICE delegates to the adapter's restart_picframe_service (#763)."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = SystemManager(mock_bus, mock_adapter)

    manager._handle_command_event(CommandEvent(command=Command.RESTART_SERVICE))

    mock_adapter.restart_picframe_service.assert_called_once()
    mock_adapter.reboot.assert_not_called()
    mock_adapter.shutdown.assert_not_called()


def test_system_manager_ignores_unrelated_command() -> None:
    """An unrelated command must not trigger any HAL power/restart call."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = SystemManager(mock_bus, mock_adapter)

    manager._handle_command_event(CommandEvent(command=Command.NEXT))

    mock_adapter.reboot.assert_not_called()
    mock_adapter.shutdown.assert_not_called()
    mock_adapter.restart_picframe_service.assert_not_called()


def test_system_manager_ignores_non_command_event() -> None:
    """A non-CommandEvent payload is silently ignored."""
    mock_bus = MagicMock()
    mock_adapter = MagicMock()
    manager = SystemManager(mock_bus, mock_adapter)

    manager._handle_command_event("not-a-command-event")  # type: ignore[arg-type]

    mock_adapter.reboot.assert_not_called()
    mock_adapter.shutdown.assert_not_called()
    mock_adapter.restart_picframe_service.assert_not_called()
