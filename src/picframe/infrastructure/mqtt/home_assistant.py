"""Home Assistant MQTT adapter for the next-gen control plane."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from picframe import __version__
from picframe.core.events.dto import (
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    State,
    StateEvent,
)
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.ports.state import ISystemStateQuery
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MqttSettings:
    """Runtime MQTT connection settings loaded from Picframe config."""

    enabled: bool
    server: str
    port: int
    login: str
    password: str
    tls: str
    device_id: str
    device_url: str


class HomeAssistantMqttAdapter:
    """Expose Picframe controls and state through Home Assistant MQTT discovery."""

    BUTTONS: dict[str, tuple[str, str, str]] = {
        "play": ("Play", "mdi:play", "play"),
        "pause": ("Pause", "mdi:pause", "pause"),
        "next": ("Next", "mdi:skip-next", "next"),
        "previous": ("Previous", "mdi:skip-previous", "previous"),
        "delete_current_left": ("Delete current / left", "mdi:delete", "delete_left"),
        "delete_right": ("Delete right", "mdi:delete-outline", "delete_right"),
        "delete_both": ("Delete both", "mdi:delete-alert", "delete_both"),
        "reboot": ("Reboot host", "mdi:restart", "reboot"),
        "shutdown": ("Shutdown host", "mdi:power", "shutdown"),
    }
    SWITCHES: dict[str, tuple[str, str, tuple[str, str] | None]] = {
        "display": ("Display", "mdi:panorama", None),
        "shuffle": ("Shuffle", "mdi:shuffle-variant", ("model", "shuffle")),
        "clock": ("Clock overlay", "mdi:clock-outline", ("viewer", "show_clock")),
        "text_overlay": (
            "Text overlay",
            "mdi:subtitles",
            ("viewer", "show_text_enabled"),
        ),
    }
    NUMBERS: dict[str, tuple[str, str, float, float, float, tuple[str, str] | None]] = {
        "brightness": ("Brightness", "mdi:brightness-6", 0.0, 1.0, 0.05, None),
        "time_delay": ("Time delay", "mdi:image-plus", 1.0, 400.0, 1.0, ("model", "time_delay")),
        "fade_time": (
            "Fade time",
            "mdi:image-size-select-large",
            1.0,
            50.0,
            1.0,
            ("model", "fade_time"),
        ),
        "mat_images": (
            "Matting images",
            "mdi:image-frame",
            0.0,
            1.0,
            0.01,
            ("viewer", "mat_images"),
        ),
    }
    TEXTS: dict[str, tuple[str, str, tuple[str, str]]] = {
        "subdirectory": ("Subdirectory", "mdi:folder", ("model", "subdirectory")),
        "date_from": ("Date from", "mdi:calendar-arrow-left", ("model", "date_from")),
        "date_to": ("Date to", "mdi:calendar-arrow-right", ("model", "date_to")),
        "location_filter": ("Location filter", "mdi:map-search", ("model", "location_filter")),
        "tags_filter": ("Tags filter", "mdi:image-search", ("model", "tags_filter")),
        "text_overlay_format": (
            "Text overlay format",
            "mdi:format-text",
            ("viewer", "text_overlay_format"),
        ),
    }
    SELECTS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, str]]] = {
        "shuffle_mode": (
            "Shuffle mode",
            "mdi:shuffle",
            ("standard", "fewer_repeats"),
            ("model", "shuffle_mode"),
        ),
    }

    def __init__(
        self,
        config_repository: IConfigRepository,
        event_publisher: IEventPublisher,
        event_subscriber: IEventSubscriber,
        state_query: ISystemStateQuery,
        client_factory: Callable[..., mqtt.Client] | None = None,
    ) -> None:
        self._config_repository = config_repository
        self._publisher = event_publisher
        self._subscriber = event_subscriber
        self._state_query = state_query
        self._client_factory = client_factory or mqtt.Client
        self._settings = self._load_settings()
        self._client: mqtt.Client | None = None
        self._connected = False
        self._events_subscribed = False
        self._display_on = True
        self._brightness = 1.0

    @property
    def enabled(self) -> bool:
        """Return whether MQTT is enabled in runtime config."""
        return self._settings.enabled

    def start(self) -> None:
        """Connect to the MQTT broker and publish Home Assistant discovery."""
        if not self._settings.enabled:
            logger.info("MQTT is disabled.")
            return

        self._subscribe_events()
        try:
            self._client = self._client_factory(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._settings.device_id,
                clean_session=True,
            )
            if self._settings.login or self._settings.password:
                self._client.username_pw_set(self._settings.login, self._settings.password)
            if self._settings.tls:
                self._client.tls_set(os.path.expanduser(self._settings.tls))

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message
            result = self._client.connect(
                self._settings.server,
                self._settings.port,
                keepalive=60,
            )
            self._connected = result == 0
            self._client.loop_start()
            logger.info(
                "MQTT adapter started for broker %s:%s",
                self._settings.server,
                self._settings.port,
            )
        except Exception as error:  # pylint: disable=broad-except
            self._connected = False
            logger.warning("MQTT adapter could not connect: %s", error)

    def stop(self) -> None:
        """Stop MQTT delivery and unsubscribe from the event bus."""
        self._unsubscribe_events()
        if self._client is None:
            return

        try:
            self._client.publish(self._availability_topic, "offline", qos=0, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as error:  # pylint: disable=broad-except
            logger.warning("MQTT adapter stop failed: %s", error)
        finally:
            self._connected = False
            self._client = None

    def publish_state(self) -> None:
        """Publish current Picframe state and config-backed entity states."""
        if self._client is None:
            return
        system_state = self._state_query.get_system_state()
        self._publish_json(self._state_topic, system_state, retain=False)

        current_media = self._state_query.get_current_media()
        if current_media:
            self._publish_media(current_media)

        self._publish_entity_state("display", "ON" if self._display_on else "OFF")
        self._publish_entity_state("brightness", self._brightness)
        for entity_id, (_, _, config_key) in self.SWITCHES.items():
            if config_key is None:
                continue
            section, key = config_key
            self._publish_entity_state(
                entity_id,
                "ON" if self._config_bool(f"{section}.{key}", False) else "OFF",
            )
        for entity_id, (_, _, _, _, _, config_key) in self.NUMBERS.items():
            if config_key is None:
                continue
            section, key = config_key
            self._publish_entity_state(entity_id, self._config_value(f"{section}.{key}", ""))
        for entity_id, (_, _, config_key) in self.TEXTS.items():
            section, key = config_key
            self._publish_entity_state(entity_id, self._config_value(f"{section}.{key}", ""))
        for entity_id, (_, _, _, config_key) in self.SELECTS.items():
            section, key = config_key
            self._publish_entity_state(
                entity_id,
                self._config_value(f"{section}.{key}", "standard"),
            )

    def _load_settings(self) -> MqttSettings:
        return MqttSettings(
            enabled=self._config_bool("mqtt.use_mqtt", False),
            server=str(self._config_value("mqtt.server", "your_mqtt_broker")),
            port=int(self._config_value("mqtt.port", 1883)),
            login=str(self._config_value("mqtt.login", "")),
            password=str(self._config_value("mqtt.password", "")),
            tls=str(self._config_value("mqtt.tls", "")),
            device_id=str(self._config_value("mqtt.device_id", "picframe")),
            device_url=str(self._config_value("mqtt.device_url", "")),
        )

    def _subscribe_events(self) -> None:
        if self._events_subscribed:
            return
        self._subscriber.subscribe(CurrentMediaChangedEvent, self._handle_media_changed)
        self._subscriber.subscribe(StateEvent, self._handle_state_changed)
        self._events_subscribed = True

    def _unsubscribe_events(self) -> None:
        if not self._events_subscribed:
            return
        self._subscriber.unsubscribe(CurrentMediaChangedEvent, self._handle_media_changed)
        self._subscriber.unsubscribe(StateEvent, self._handle_state_changed)
        self._events_subscribed = False

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: object,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode | int,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if not self._reason_code_ok(reason_code):
            logger.warning("MQTT broker rejected connection: %s", reason_code)
            self._connected = False
            return

        self._connected = True
        client.publish(self._availability_topic, "online", qos=0, retain=True)
        self._publish_discovery()
        for topic in self._command_topics:
            client.subscribe(topic, qos=0)
        self.publish_state()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode | int | None,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        self._connected = False
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic = str(message.topic)
        payload = message.payload.decode("utf-8").strip()
        action = self._command_topics.get(topic)
        if action is None:
            logger.debug("Ignoring unknown MQTT topic: %s", topic)
            return

        try:
            self._handle_action(action, payload)
        except Exception as error:  # pylint: disable=broad-except
            logger.warning("MQTT action failed for %s: %s", topic, error)

    def _handle_action(self, action: str, payload: str) -> None:
        if action == "play":
            self._publish_command(Command.PLAY)
        elif action == "pause":
            self._publish_command(Command.PAUSE)
        elif action == "next":
            self._publish_command(Command.NEXT)
        elif action == "previous":
            self._publish_command(Command.PREV)
        elif action == "reboot":
            self._publish_command(Command.REBOOT_HOST)
        elif action == "shutdown":
            self._publish_command(Command.SHUTDOWN_HOST)
        elif action == "delete_left":
            self._publish_delete("left")
        elif action == "delete_right":
            self._publish_delete("right")
        elif action == "delete_both":
            self._publish_delete("both")
        elif action == "display":
            enabled = self._payload_bool(payload)
            self._display_on = enabled
            self._publish_command(Command.DISPLAY_ON if enabled else Command.DISPLAY_OFF)
            self._publish_entity_state("display", "ON" if enabled else "OFF")
        elif action == "brightness":
            value = float(payload)
            self._brightness = value
            self._publish_command(Command.SET_BRIGHTNESS, value)
            self._publish_entity_state("brightness", value)
        elif action.startswith("config:"):
            _prefix, section, key, value_type = action.split(":", 3)
            value = self._coerce_config_value(payload, value_type)
            self._publish_config(section, key, value)
            entity_id = self._entity_for_config(section, key)
            if entity_id:
                state_value: Any = "ON" if value is True else "OFF" if value is False else value
                self._publish_entity_state(entity_id, state_value)

    def _publish_discovery(self) -> None:
        for entity_id, (name, icon, _action) in self.BUTTONS.items():
            self._publish_discovery_payload(
                "button",
                entity_id,
                {
                    "name": name,
                    "icon": icon,
                    "command_topic": self._button_topic(entity_id),
                    "payload_press": "PRESS",
                },
            )

        self._publish_discovery_payload(
            "sensor",
            "state",
            {
                "name": "State",
                "icon": "mdi:play-circle",
                "state_topic": self._state_topic,
                "value_template": "{{ value_json.state }}",
            },
        )
        self._publish_discovery_payload(
            "sensor",
            "current_media",
            {
                "name": "Current media",
                "icon": "mdi:file-image",
                "state_topic": self._media_state_topic,
                "value_template": "{{ value_json.filename }}",
                "json_attributes_topic": self._media_attributes_topic,
            },
        )

        for entity_id, (name, icon, _config_key) in self.SWITCHES.items():
            self._publish_discovery_payload(
                "switch",
                entity_id,
                {
                    "name": name,
                    "icon": icon,
                    "state_topic": self._entity_state_topic(entity_id),
                    "command_topic": self._entity_command_topic(entity_id),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                },
            )

        for entity_id, (name, icon, minimum, maximum, step, _config_key) in self.NUMBERS.items():
            self._publish_discovery_payload(
                "number",
                entity_id,
                {
                    "name": name,
                    "icon": icon,
                    "min": minimum,
                    "max": maximum,
                    "step": step,
                    "state_topic": self._entity_state_topic(entity_id),
                    "command_topic": self._entity_command_topic(entity_id),
                },
            )

        for entity_id, (name, icon, _config_key) in self.TEXTS.items():
            self._publish_discovery_payload(
                "text",
                entity_id,
                {
                    "name": name,
                    "icon": icon,
                    "state_topic": self._entity_state_topic(entity_id),
                    "command_topic": self._entity_command_topic(entity_id),
                },
            )

        for entity_id, (name, icon, options, _config_key) in self.SELECTS.items():
            self._publish_discovery_payload(
                "select",
                entity_id,
                {
                    "name": name,
                    "icon": icon,
                    "options": list(options),
                    "state_topic": self._entity_state_topic(entity_id),
                    "command_topic": self._entity_command_topic(entity_id),
                },
            )

    def _publish_discovery_payload(
        self,
        component: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self._client is None:
            return
        object_id = f"{self._settings.device_id}_{entity_id}"
        config = {
            **payload,
            "unique_id": object_id,
            "availability_topic": self._availability_topic,
            "device": self._device_payload(),
        }
        topic = f"homeassistant/{component}/{object_id}/config"
        self._client.publish(topic, json.dumps(config), qos=0, retain=True)

    def _handle_media_changed(self, event: CurrentMediaChangedEvent) -> None:
        media = self._media_to_dict(event.media_item)
        self._publish_media(media)

    def _handle_state_changed(self, event: StateEvent) -> None:
        if self._client is None:
            return
        state = self._state_query.get_system_state()
        state["state"] = event.state.name
        state["is_playing"] = event.state == State.PLAYING
        state["is_paused"] = event.state == State.PAUSED
        state["is_sleeping"] = event.state == State.SLEEPING
        self._publish_json(self._state_topic, state, retain=False)

    def _publish_media(self, media: dict[str, Any]) -> None:
        if self._client is None:
            return
        filepath = str(media.get("filepath") or media.get("file_path") or "")
        filename = str(media.get("filename") or Path(filepath).name or "")
        state = {
            "filename": filename,
            "layout": media.get("layout", "single"),
            "id": media.get("id"),
        }
        self._publish_json(self._media_state_topic, state, retain=False)
        self._publish_json(self._media_attributes_topic, media, retain=False)

    def _publish_delete(self, target: str) -> None:
        if target in {"right", "both"} and not self._current_media_is_pair():
            logger.warning(
                "Ignoring MQTT delete-%s because current media is not a portrait pair.",
                target,
            )
            return
        self._publish_command(Command.DELETE, {"target": target})

    def _publish_command(self, command: Command, payload: Any = None) -> None:
        self._publisher.publish(CommandEvent(command=command, payload=payload))

    def _publish_config(self, section: str, key: str, value: Any) -> None:
        self._publish_command(Command.SET_CONFIG, {section: {key: value}})

    @property
    def _command_topics(self) -> dict[str, str]:
        mapping: dict[str, str] = {
            self._button_topic(entity_id): action
            for entity_id, (_name, _icon, action) in self.BUTTONS.items()
        }
        mapping[self._entity_command_topic("display")] = "display"
        mapping[self._entity_command_topic("brightness")] = "brightness"

        for entity_id, (_name, _icon, config_key) in self.SWITCHES.items():
            if config_key is None:
                continue
            section, key = config_key
            mapping[self._entity_command_topic(entity_id)] = f"config:{section}:{key}:bool"
        for entity_id, (
            _name,
            _icon,
            _minimum,
            _maximum,
            _step,
            config_key,
        ) in self.NUMBERS.items():
            if config_key is None:
                continue
            section, key = config_key
            mapping[self._entity_command_topic(entity_id)] = f"config:{section}:{key}:float"
        for entity_id, (_name, _icon, config_key) in self.TEXTS.items():
            section, key = config_key
            mapping[self._entity_command_topic(entity_id)] = f"config:{section}:{key}:str"
        for entity_id, (_name, _icon, _options, config_key) in self.SELECTS.items():
            section, key = config_key
            mapping[self._entity_command_topic(entity_id)] = f"config:{section}:{key}:str"
        return mapping

    def _entity_for_config(self, section: str, key: str) -> str | None:
        for entity_id, (_name, _icon, config_key) in self.SWITCHES.items():
            if config_key == (section, key):
                return entity_id
        for entity_id, (
            _name,
            _icon,
            _minimum,
            _maximum,
            _step,
            config_key,
        ) in self.NUMBERS.items():
            if config_key == (section, key):
                return entity_id
        for entity_id, (_name, _icon, config_key) in self.TEXTS.items():
            if config_key == (section, key):
                return entity_id
        for entity_id, (_name, _icon, _options, config_key) in self.SELECTS.items():
            if config_key == (section, key):
                return entity_id
        return None

    def _device_payload(self) -> dict[str, Any]:
        payload = {
            "identifiers": [self._settings.device_id],
            "name": self._settings.device_id,
            "model": "PictureFrame",
            "manufacturer": "pi3d PictureFrame project",
            "sw_version": __version__,
        }
        if self._settings.device_url:
            payload["configuration_url"] = self._settings.device_url
        return payload

    def _current_media_is_pair(self) -> bool:
        current = self._state_query.get_current_media()
        return bool(current and current.get("layout") == "portrait_pair")

    def _media_to_dict(self, media_item: Any) -> dict[str, Any]:
        if hasattr(media_item, "to_dict") and callable(media_item.to_dict):
            media = media_item.to_dict()
        elif isinstance(media_item, dict):
            media = dict(media_item)
        elif hasattr(media_item, "__dict__"):
            media = dict(media_item.__dict__)
        else:
            media = {"raw": str(media_item)}
        return media

    def _publish_entity_state(self, entity_id: str, value: Any) -> None:
        self._publish_raw(self._entity_state_topic(entity_id), str(value), retain=True)

    def _publish_json(self, topic: str, payload: dict[str, Any], retain: bool) -> None:
        self._publish_raw(topic, json.dumps(payload), retain=retain)

    def _publish_raw(self, topic: str, payload: str, retain: bool) -> None:
        if self._client is not None:
            self._client.publish(topic, payload, qos=0, retain=retain)

    def _config_value(self, key: str, default: Any) -> Any:
        return self._config_repository.get_app_config(key, default)

    def _config_bool(self, key: str, default: bool) -> bool:
        if hasattr(self._config_repository, "get_app_config_bool"):
            return self._config_repository.get_app_config_bool(key, default)
        value = self._config_repository.get_app_config(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _coerce_config_value(payload: str, value_type: str) -> Any:
        if value_type == "bool":
            return HomeAssistantMqttAdapter._payload_bool(payload)
        if value_type == "float":
            return float(payload)
        return payload

    @staticmethod
    def _payload_bool(payload: str) -> bool:
        return payload.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _reason_code_ok(reason_code: mqtt.ReasonCode | int) -> bool:
        return int(getattr(reason_code, "value", reason_code)) == 0

    @property
    def _base_topic(self) -> str:
        return f"picframe/{self._settings.device_id}"

    @property
    def _availability_topic(self) -> str:
        return f"{self._base_topic}/availability"

    @property
    def _state_topic(self) -> str:
        return f"{self._base_topic}/state"

    @property
    def _media_state_topic(self) -> str:
        return f"{self._base_topic}/media/state"

    @property
    def _media_attributes_topic(self) -> str:
        return f"{self._base_topic}/media/attributes"

    def _entity_state_topic(self, entity_id: str) -> str:
        return f"{self._base_topic}/{entity_id}/state"

    def _entity_command_topic(self, entity_id: str) -> str:
        return f"{self._base_topic}/{entity_id}/set"

    def _button_topic(self, entity_id: str) -> str:
        return f"{self._base_topic}/{entity_id}/press"
