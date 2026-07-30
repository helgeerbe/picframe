"""
System Manager Service.

This module provides the `SystemManager` service, which subscribes
to the Event Bus and delegates system-level commands (like reboot and shutdown)
to the injected Hardware Abstraction Layer (HAL) adapter.
"""

import logging
from typing import Any

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.ports import ISystemManager

logger = logging.getLogger(__name__)


class SystemManager:
    """
    Service responsible for managing system-level operations.
    """

    def __init__(self, event_bus: IEventSubscriber, system_manager_adapter: ISystemManager) -> None:
        """
        Initialize the SystemManager.

        Args:
            event_bus: The event bus subscriber interface.
            system_manager_adapter: The injected HAL adapter for system operations.
        """
        self._event_bus = event_bus
        self._adapter = system_manager_adapter
        self._subscribe()
        logger.info("SystemManager initialized.")

    def _subscribe(self) -> None:
        """Subscribe to relevant events on the Event Bus."""
        self._event_bus.subscribe(CommandEvent, self._handle_command_event)

    def _handle_command_event(self, event: Any) -> None:
        """
        Handle incoming CommandEvents.

        Args:
            event: The CommandEvent instance.
        """
        if not isinstance(event, CommandEvent):
            return

        if event.command == Command.REBOOT_HOST:
            logger.info("SystemManager: Received REBOOT_HOST command.")
            self._adapter.reboot()
        elif event.command == Command.SHUTDOWN_HOST:
            logger.info("SystemManager: Received SHUTDOWN_HOST command.")
            self._adapter.shutdown()
