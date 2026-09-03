"""
Configuration Service.

This module provides a service to handle configuration updates received
via the EventBus (e.g., from the WebUI) and persist them to the database.
"""

import logging
from typing import Any

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    OverlayConfigChangedEvent,
    RendererConfigUpdatedEvent,
    State,
    StateEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.hardware_input import normalize_hardware_inputs_config
from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.services.renderer_config import build_renderer_config
from picframe.core.services.resource_paths import ResourcePaths

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
        resource_paths: ResourcePaths | None = None,
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
        self._resource_paths = resource_paths

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
            "hardware_inputs": {},
            "overlay": {},
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
                "hardware_inputs": self._config_repository.get_app_config("hardware_inputs", {}),
                "overlay": self._config_repository.get_app_config("overlay", {}),
            }

        return config

    def update_nested_config(self, nested_config: dict[str, Any]) -> None:
        """
        Flattens nested dict and updates the repository.
        """
        if not self._config_repository:
            logger.warning("Cannot update config: no config repository is available")
            return

        if "hardware_inputs" in nested_config:
            nested_config = dict(nested_config)
            nested_config["hardware_inputs"] = normalize_hardware_inputs_config(
                nested_config["hardware_inputs"]
            )

        def flatten_dict(d: dict[str, Any], parent_key: str = "") -> dict[str, Any]:
            items: list[tuple[str, Any]] = []
            for k, v in d.items():
                new_key = f"{parent_key}.{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(flatten_dict(v, new_key).items())
                else:
                    items.append((new_key, v))
            return dict(items)

        flat_payload = flatten_dict(nested_config)
        if "hardware_inputs" in nested_config:
            self._config_repository.delete_app_config_prefix("hardware_inputs")
        for key, value in flat_payload.items():
            self._config_repository.set_app_config(key, value)

    def update_plugin_config(self, plugin_id: str, plugin_config: dict[str, Any]) -> None:
        """Persist a single plugin's config under ``overlay.plugin_config.<id>.*``.

        Reuses the same ``delete_app_config_prefix`` + re-write pattern as
        ``hardware_inputs``, but scoped to one plugin so the rest of the
        ``overlay`` section is never wiped. Stale keys from a previous version
        of the plugin config are removed before the new values are written.
        """
        if not self._config_repository:
            logger.warning("Cannot update plugin config: no config repository is available")
            return

        prefix = f"overlay.plugin_config.{plugin_id}"
        self._config_repository.delete_app_config_prefix(prefix)
        for key, value in plugin_config.items():
            self._config_repository.set_app_config(f"{prefix}.{key}", value)

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
                        state=State.CONFIG_CHANGED, payload={"updated_sections": updated_sections}
                    )
                )

                if (
                    "viewer" in updated_sections
                    or "model" in updated_sections
                    or "text_overlay" in updated_sections
                ):
                    self._publish_renderer_config()

                if "overlay" in updated_sections:
                    self._publish_overlay_config_changed(payload["overlay"])

        except Exception as e:
            logger.error(f"Error processing SET_CONFIG payload: {e}", exc_info=True)

    def _publish_overlay_config_changed(self, overlay_payload: Any) -> None:
        """Publish an ``OverlayConfigChangedEvent`` with the merged overlay config.

        ``overlay_payload`` is the ``overlay`` section of the SET_CONFIG payload.
        When it contains only a ``plugin_config`` with a single plugin id, that id
        is reported as ``updated_plugin_id`` so subscribers can scope their work.
        """
        if not self._config_repository:
            return

        try:
            nested = self.get_nested_config()
            overlay_config = nested.get("overlay", {})
            updated_plugin_id: str | None = None
            if isinstance(overlay_payload, dict):
                plugin_config = overlay_payload.get("plugin_config")
                if isinstance(plugin_config, dict) and len(plugin_config) == 1:
                    updated_plugin_id = next(iter(plugin_config))
            self._event_publisher.publish(
                OverlayConfigChangedEvent(
                    overlay_config=dict(overlay_config),
                    updated_plugin_id=updated_plugin_id,
                )
            )
        except Exception as e:
            logger.error(f"Failed to publish OverlayConfigChangedEvent: {e}", exc_info=True)

    def _publish_renderer_config(self) -> None:
        """
        Constructs and publishes a RendererConfigUpdatedEvent.
        """
        if not self._config_repository:
            return

        try:
            config = build_renderer_config(self._config_repository, self._resource_paths)
            self._event_publisher.publish(RendererConfigUpdatedEvent(config=config))
        except Exception as e:
            logger.error(f"Failed to publish RendererConfigUpdatedEvent: {e}", exc_info=True)
