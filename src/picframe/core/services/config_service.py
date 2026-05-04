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

    def get_nested_config(self) -> dict[str, Any]:
        """
        Fetches flat config from repo and transforms to nested dict.
        """
        if not self._config_repository:
            return {}
            
        config: dict[str, Any] = {
            "viewer": {},
            "model": {},
            "mqtt": {},
            "http": {},
            "peripherals": {},
        }
        
        if hasattr(self._config_repository, "get_all_app_config"):
            all_config = self._config_repository.get_all_app_config()
            for key, value in all_config.items():
                parts = key.split(".")
                if len(parts) >= 2:
                    section = parts[0]
                    if section in config:
                        current = config[section]
                        for part in parts[1:-1]:
                            if part not in current:
                                current[part] = {}
                            current = current[part]
                        current[parts[-1]] = value
        else:
            # Fallback for tests that mock get_app_config
            config = {
                "viewer": self._config_repository.get_app_config("viewer", {}),
                "model": self._config_repository.get_app_config("model", {}),
                "mqtt": self._config_repository.get_app_config("mqtt", {}),
                "http": self._config_repository.get_app_config("http", {}),
                "peripherals": self._config_repository.get_app_config("peripherals", {}),
            }
            
        return config

    def update_nested_config(self, nested_config: dict[str, Any]) -> None:
        """
        Flattens nested dict and updates the repository.
        """
        if not self._config_repository:
            logger.warning("Cannot update config: no config repository is available")
            return
            
        def flatten_dict(d: dict[str, Any], parent_key: str = '') -> dict[str, Any]:
            items: list[tuple[str, Any]] = []
            for k, v in d.items():
                new_key = f"{parent_key}.{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(flatten_dict(v, new_key).items())
                else:
                    items.append((new_key, v))
            return dict(items)

        flat_payload = flatten_dict(nested_config)
        for key, value in flat_payload.items():
            self._config_repository.set_app_config(key, value)

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

        try:
            self.update_nested_config(payload)
            updated_sections = list(payload.keys())

            if updated_sections:
                logger.info(f"Configuration updated for sections: {updated_sections}")
                # Publish state change event
                self._event_publisher.publish(
                    StateEvent(
                        state=State.CONFIG_CHANGED,
                        payload={"updated_sections": updated_sections}
                    )
                )

        except Exception as e:
            logger.error(f"Error processing SET_CONFIG payload: {e}", exc_info=True)
