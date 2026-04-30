"""
Display Power Manager Service.

This module provides the `DisplayPowerManager` service, which subscribes
to the Event Bus and delegates display power commands to the injected
Hardware Abstraction Layer (HAL) adapter.
"""

import logging
from typing import Any

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.ports import IDisplayPower

logger = logging.getLogger(__name__)


class DisplayPowerManager:
    """
    Service responsible for managing the physical display power state.
    """

    def __init__(
        self, event_bus: IEventSubscriber, display_power_adapter: IDisplayPower
    ) -> None:
        """
        Initialize the DisplayPowerManager.

        Args:
            event_bus: The event bus subscriber interface.
            display_power_adapter: The injected HAL adapter for display power.
        """
        self._event_bus = event_bus
        self._adapter = display_power_adapter
        self._subscribe()
        logger.info("DisplayPowerManager initialized.")

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

        if event.command == Command.DISPLAY_ON:
            logger.info("DisplayPowerManager: Received DISPLAY_ON command.")
            self._adapter.turn_on()
        elif event.command == Command.DISPLAY_OFF:
            logger.info("DisplayPowerManager: Received DISPLAY_OFF command.")
            self._adapter.turn_off()
        elif event.command == Command.DISPLAY_TOGGLE:
            logger.info("DisplayPowerManager: Received DISPLAY_TOGGLE command.")
            self._adapter.toggle()
        elif event.command == Command.SET_BRIGHTNESS:
            if event.payload is not None:
                try:
                    brightness = float(event.payload)
                    # Ensure brightness is within 0.0 to 1.0 bounds
                    brightness = max(0.0, min(1.0, brightness))
                    logger.info(f"DisplayPowerManager: Received SET_BRIGHTNESS command ({brightness}).")
                    self._adapter.set_brightness(brightness)
                except ValueError:
                    logger.error(f"DisplayPowerManager: Invalid brightness payload: {event.payload}")
