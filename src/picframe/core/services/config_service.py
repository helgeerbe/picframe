"""
Configuration Service.

This module provides a service to handle configuration updates received
via the EventBus (e.g., from the WebUI) and persist them to the database.
"""

import logging
from typing import Any

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)


class ConfigService:
    """
    Service responsible for handling configuration updates.

    Listens for SET_CONFIG commands, updates the configuration repository,
    and publishes a CONFIG_CHANGED state event.
    """

    def __init__(
        self,
        config_repository: IConfigRepository,
        event_subscriber: IEventSubscriber,
        event_publisher: IEventPublisher,
    ) -> None:
        """
        Initialize the ConfigService.

        Args:
            config_repository: The repository for persisting configuration.
            event_subscriber: The event bus subscriber to listen for commands.
            event_publisher: The event bus publisher to emit state changes.
        """
        self._config_repository = config_repository
        self._event_publisher = event_publisher
        self._event_subscriber = event_subscriber

        # Subscribe to SET_CONFIG commands
        self._event_subscriber.subscribe(CommandEvent, self._handle_command_event)
        logger.info("ConfigService initialized and subscribed to CommandEvent.")

    def _handle_command_event(self, event: Any) -> None:
        """
        Handle incoming CommandEvents.

        Args:
            event: The event to process.
        """
        if not isinstance(event, CommandEvent):
            return

        if event.command == Command.SET_CONFIG:
            self._handle_set_config(event.payload)

    def _handle_set_config(self, payload: Any) -> None:
        """
        Process a SET_CONFIG payload.

        Args:
            payload: A dictionary containing configuration updates.
                     Expected format: {"section": {"key": value, ...}, ...}
        """
        if not isinstance(payload, dict):
            logger.warning(f"Invalid SET_CONFIG payload type: {type(payload)}. Expected dict.")
            return

        updated_sections = []
        try:
            for section, settings in payload.items():
                if not isinstance(settings, dict):
                    logger.warning(f"Invalid settings format for section '{section}'. Expected dict.")
                    continue

                for key, value in settings.items():
                    config_key = f"{section}.{key}"
                    self._config_repository.set_app_config(config_key, value)
                    logger.debug(f"Updated config: {config_key} = {value}")
                
                updated_sections.append(section)

            if updated_sections:
                logger.info(f"Configuration updated for sections: {updated_sections}")
                # Publish state change event
                self._event_publisher.publish(
                    StateEvent(state=State.CONFIG_CHANGED, payload={"updated_sections": updated_sections})
                )

        except Exception as e:
            logger.error(f"Error processing SET_CONFIG payload: {e}", exc_info=True)
