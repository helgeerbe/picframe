"""
Display Power Manager Service.

This module provides the `DisplayPowerManager` service, which subscribes
to the Event Bus and delegates display power commands to the injected
Hardware Abstraction Layer (HAL) adapter.
"""

import logging
from typing import Any

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.ports import IDisplayPower
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)


class DisplayPowerManager:
    """
    Service responsible for managing the physical display power state.
    """

    def __init__(
        self,
        event_bus: IEventSubscriber,
        display_power_adapter: IDisplayPower,
        config_repository: IConfigRepository | None = None,
        event_publisher: IEventPublisher | None = None,
    ) -> None:
        """
        Initialize the DisplayPowerManager.

        Args:
            event_bus: The event bus subscriber interface.
            display_power_adapter: The injected HAL adapter for display power.
        """
        self._event_bus = event_bus
        self._adapter = display_power_adapter
        self._config_repository = config_repository
        self._event_publisher = event_publisher
        self._subscribe()
        logger.info("DisplayPowerManager initialized.")

    def _subscribe(self) -> None:
        """Subscribe to relevant events on the Event Bus."""
        self._event_bus.subscribe(CommandEvent, self._handle_command_event)
        self._event_bus.subscribe(StateEvent, self._handle_state_event)

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
            if self._adapter.is_on():
                logger.debug("DisplayPowerManager: Display already ON; ignoring DISPLAY_ON.")
                return
            self._adapter.turn_on()
            self._publish_playback_command(Command.PLAY)
        elif event.command == Command.DISPLAY_OFF:
            logger.info("DisplayPowerManager: Received DISPLAY_OFF command.")
            if not self._adapter.is_on():
                logger.debug("DisplayPowerManager: Display already OFF; ignoring DISPLAY_OFF.")
                return
            self._adapter.turn_off()
            self._publish_playback_command(Command.PAUSE)
        elif event.command == Command.DISPLAY_TOGGLE:
            logger.info("DisplayPowerManager: Received DISPLAY_TOGGLE command.")
            self._adapter.toggle()
            self._publish_playback_command(Command.PLAY if self._adapter.is_on() else Command.PAUSE)
        elif event.command == Command.SET_BRIGHTNESS:
            if event.payload is not None:
                try:
                    brightness = float(event.payload)
                    # Ensure brightness is within 0.0 to 1.0 bounds
                    brightness = max(0.0, min(1.0, brightness))
                    logger.info(
                        "DisplayPowerManager: Received SET_BRIGHTNESS command (%s).",
                        brightness,
                    )
                    self._adapter.set_brightness(brightness)
                except ValueError:
                    logger.error(
                        "DisplayPowerManager: Invalid brightness payload: %s",
                        event.payload,
                    )

    def _publish_playback_command(self, command: Command) -> None:
        if self._event_publisher is None:
            return
        self._event_publisher.publish(CommandEvent(command=command))

    def _handle_state_event(self, event: Any) -> None:
        """Retarget display-power commands after live viewer config changes."""
        if not isinstance(event, StateEvent):
            return
        if event.state != State.CONFIG_CHANGED or self._config_repository is None:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])
        if "viewer" not in updated_sections:
            return

        display_output = str(
            self._config_repository.get_app_config("viewer.display_hdmi", "HDMI-A-1")
        )
        self._adapter.set_display_output(display_output)
