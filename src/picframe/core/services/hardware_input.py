"""
Hardware Input Service.

This module provides the `HardwareInputService`, which listens for hardware
events (like button presses or PIR sensor triggers) from the injected
Hardware Abstraction Layer (HAL) adapter and translates them into
`CommandEvent`s published to the Event Bus.
"""

import logging
from typing import Any, Dict

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.ports import IHardwareInput

logger = logging.getLogger(__name__)


class HardwareInputService:
    """
    Service responsible for translating hardware inputs into system commands.
    """

    def __init__(
        self,
        event_bus: IEventPublisher,
        hardware_input_adapter: IHardwareInput,
        input_mapping: Dict[str, Dict[str, str]],
    ) -> None:
        """
        Initialize the HardwareInputService.

        Args:
            event_bus: The event bus publisher interface.
            hardware_input_adapter: The injected HAL adapter for hardware inputs.
            input_mapping: A dictionary mapping input IDs and actions to commands.
                           Format: { "input_id": { "action": "COMMAND_NAME" } }
                           Example: { "next_button": { "pressed": "NEXT" } }
        """
        self._event_bus = event_bus
        self._adapter = hardware_input_adapter
        self._mapping = input_mapping

        # Register the callback with the adapter
        self._adapter.register_callback(self._handle_hardware_event)
        logger.info("HardwareInputService initialized.")

    def _handle_hardware_event(self, input_id: str, action: str) -> None:
        """
        Callback invoked by the HAL adapter when a hardware event occurs.

        Args:
            input_id: The ID of the hardware input (e.g., 'next_button').
            action: The action that occurred (e.g., 'pressed', 'motion_detected').
        """
        logger.debug(f"HardwareInputService: Received event {input_id} -> {action}")

        device_mapping = self._mapping.get(input_id)
        if not device_mapping:
            logger.warning(f"HardwareInputService: No mapping found for input '{input_id}'")
            return

        command_name = device_mapping.get(action)
        if not command_name:
            logger.warning(
                f"HardwareInputService: No command mapped for action '{action}' on input '{input_id}'"
            )
            return

        try:
            command = Command[command_name]
            logger.info(f"HardwareInputService: Translating {input_id}:{action} to {command.name}")
            self._event_bus.publish(CommandEvent(command=command))
        except KeyError:
            logger.error(f"HardwareInputService: Invalid command name '{command_name}' in mapping.")

    def start(self) -> None:
        """Start the underlying hardware input adapter."""
        logger.info("HardwareInputService: Starting hardware monitoring.")
        self._adapter.start()

    def stop(self) -> None:
        """Stop the underlying hardware input adapter."""
        logger.info("HardwareInputService: Stopping hardware monitoring.")
        self._adapter.stop()
