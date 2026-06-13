from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt

from picframe.core.events.dto import (
    Command,
    CommandEvent,
    CurrentMediaChangedEvent,
    State,
    StateEvent,
)
from picframe.infrastructure.mqtt import HomeAssistantMqttAdapter


class FakeConfigRepository:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = {
            "mqtt.use_mqtt": True,
            "mqtt.server": "broker",
            "mqtt.port": 1883,
            "mqtt.login": "user",
            "mqtt.password": "pass",
            "mqtt.tls": "",
            "mqtt.device_id": "picframe_test",
            "mqtt.device_url": "http://picframe.local",
            "model.shuffle": True,
            "model.shuffle_mode": "standard",
            "model.time_delay": 200.0,
            "model.fade_time": 10.0,
            "model.subdirectory": "",
            "model.date_from": "",
            "model.date_to": "",
            "model.location_filter": "",
            "model.tags_filter": "",
            "viewer.mat_images": 0.01,
            "viewer.show_clock": False,
            "viewer.show_text_enabled": True,
            "viewer.text_overlay_format": "title caption name date folder location",
        }
        if values:
            self.values.update(values)

    def get_app_config(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_app_config_bool(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


class FakeSubscriber:
    def __init__(self) -> None:
        self.callbacks: dict[type, list[Any]] = {}
        self.unsubscribed: list[tuple[type, Any]] = []

    def subscribe(self, event_type: type, callback: Any) -> None:
        self.callbacks.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: type, callback: Any) -> None:
        self.unsubscribed.append((event_type, callback))


class FakeStateQuery:
    def __init__(self, media: dict[str, Any] | None = None) -> None:
        self.media = media or {"filepath": "/photos/current.jpg", "filename": "current.jpg"}
        self.state = {
            "state": "PLAYING",
            "is_playing": True,
            "is_paused": False,
            "is_sleeping": False,
        }

    def get_current_media(self) -> dict[str, Any] | None:
        return self.media

    def get_system_state(self) -> dict[str, Any]:
        return dict(self.state)


class FakeMqttClient:
    instances: list[FakeMqttClient] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.username: tuple[str, str] | None = None
        self.tls_path: str | None = None
        self.connected_to: tuple[str, int, int] | None = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.on_connect: Any = None
        self.on_disconnect: Any = None
        self.on_message: Any = None
        FakeMqttClient.instances.append(self)

    def username_pw_set(self, username: str, password: str) -> None:
        self.username = (username, password)

    def tls_set(self, ca_certs: str) -> None:
        self.tls_path = ca_certs

    def connect(self, host: str, port: int, keepalive: int) -> int:
        self.connected_to = (host, port, keepalive)
        return 0

    def loop_start(self) -> None:
        self.loop_started = True

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        self.disconnected = True

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload, qos, retain))

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append((topic, qos))


@dataclass
class FakeMessage:
    topic: str
    payload_text: str

    @property
    def payload(self) -> bytes:
        return self.payload_text.encode("utf-8")


def build_adapter(
    config: FakeConfigRepository | None = None,
    state_query: FakeStateQuery | None = None,
) -> tuple[HomeAssistantMqttAdapter, FakePublisher, FakeSubscriber, FakeStateQuery]:
    FakeMqttClient.instances = []
    publisher = FakePublisher()
    subscriber = FakeSubscriber()
    state_query = state_query or FakeStateQuery()
    adapter = HomeAssistantMqttAdapter(
        config_repository=config or FakeConfigRepository(),
        event_publisher=publisher,
        event_subscriber=subscriber,
        state_query=state_query,
        client_factory=FakeMqttClient,
    )
    return adapter, publisher, subscriber, state_query


def connect_adapter(adapter: HomeAssistantMqttAdapter) -> FakeMqttClient:
    adapter.start()
    client = FakeMqttClient.instances[-1]
    client.on_connect(client, None, None, 0, None)
    return client


def send(client: FakeMqttClient, topic: str, payload: str = "PRESS") -> None:
    client.on_message(client, None, FakeMessage(topic, payload))


def test_disabled_mqtt_does_not_create_client() -> None:
    adapter, _publisher, subscriber, _state = build_adapter(
        FakeConfigRepository({"mqtt.use_mqtt": False})
    )

    adapter.start()

    assert FakeMqttClient.instances == []
    assert CurrentMediaChangedEvent in subscriber.callbacks
    assert StateEvent in subscriber.callbacks


def test_disabled_mqtt_can_connect_after_live_enable() -> None:
    config = FakeConfigRepository({"mqtt.use_mqtt": False})
    adapter, _publisher, subscriber, _state = build_adapter(config)

    adapter.start()
    config.values["mqtt.use_mqtt"] = True
    state_callback = subscriber.callbacks[StateEvent][0]
    state_callback(
        StateEvent(
            state=State.CONFIG_CHANGED,
            payload={"updated_sections": ["mqtt"]},
        )
    )

    assert len(FakeMqttClient.instances) == 1
    assert FakeMqttClient.instances[0].connected_to == ("broker", 1883, 60)


def test_mqtt_config_change_reconnects_client() -> None:
    config = FakeConfigRepository()
    adapter, _publisher, subscriber, _state = build_adapter(config)
    first_client = connect_adapter(adapter)

    config.values["mqtt.server"] = "new-broker"
    config.values["mqtt.device_id"] = "picframe_new"
    state_callback = subscriber.callbacks[StateEvent][0]
    state_callback(
        StateEvent(
            state=State.CONFIG_CHANGED,
            payload={"updated_sections": ["mqtt"]},
        )
    )

    assert first_client.loop_stopped is True
    assert first_client.disconnected is True
    assert (
        "picframe/picframe_test/availability",
        "offline",
        0,
        True,
    ) in first_client.published
    second_client = FakeMqttClient.instances[-1]
    assert second_client is not first_client
    assert second_client.connected_to == ("new-broker", 1883, 60)
    assert second_client.kwargs["client_id"] == "picframe_new"


def test_start_connects_and_publishes_home_assistant_discovery() -> None:
    adapter, _publisher, _subscriber, _state = build_adapter()

    client = connect_adapter(adapter)

    assert client.kwargs == {
        "callback_api_version": mqtt.CallbackAPIVersion.VERSION2,
        "client_id": "picframe_test",
        "clean_session": True,
    }
    assert client.username == ("user", "pass")
    assert client.connected_to == ("broker", 1883, 60)
    assert client.loop_started is True

    discovery_topics = [topic for topic, _payload, _qos, retain in client.published if retain]
    assert "homeassistant/button/picframe_test_reboot/config" in discovery_topics
    assert "homeassistant/button/picframe_test_shutdown/config" in discovery_topics
    assert "homeassistant/button/picframe_test_delete_current_left/config" in discovery_topics
    assert "homeassistant/button/picframe_test_delete_right/config" in discovery_topics
    assert "homeassistant/button/picframe_test_delete_both/config" in discovery_topics
    assert not any("purge" in topic or "clear_cache" in topic for topic in discovery_topics)


def test_mqtt_buttons_publish_core_commands() -> None:
    adapter, publisher, _subscriber, _state = build_adapter()
    client = connect_adapter(adapter)

    send(client, "picframe/picframe_test/next/press")
    send(client, "picframe/picframe_test/previous/press")
    send(client, "picframe/picframe_test/reboot/press")
    send(client, "picframe/picframe_test/shutdown/press")

    commands = [event.command for event in publisher.events]
    assert commands == [
        Command.NEXT,
        Command.PREV,
        Command.REBOOT_HOST,
        Command.SHUTDOWN_HOST,
    ]


def test_mqtt_config_and_brightness_commands_publish_expected_payloads() -> None:
    adapter, publisher, _subscriber, _state = build_adapter()
    client = connect_adapter(adapter)

    send(client, "picframe/picframe_test/shuffle/set", "OFF")
    send(client, "picframe/picframe_test/shuffle_mode/set", "fewer_repeats")
    send(client, "picframe/picframe_test/time_delay/set", "42")
    send(client, "picframe/picframe_test/brightness/set", "0.5")

    assert publisher.events[-4:] == [
        CommandEvent(command=Command.SET_CONFIG, payload={"model": {"shuffle": False}}),
        CommandEvent(
            command=Command.SET_CONFIG,
            payload={"model": {"shuffle_mode": "fewer_repeats"}},
        ),
        CommandEvent(command=Command.SET_CONFIG, payload={"model": {"time_delay": 42.0}}),
        CommandEvent(command=Command.SET_BRIGHTNESS, payload=0.5),
    ]


def test_mqtt_pair_delete_buttons_are_targeted() -> None:
    state = FakeStateQuery(
        {
            "layout": "portrait_pair",
            "items": [{"id": 1, "filepath": "/left.jpg"}, {"id": 2, "filepath": "/right.jpg"}],
        }
    )
    adapter, publisher, _subscriber, _state = build_adapter(state_query=state)
    client = connect_adapter(adapter)

    send(client, "picframe/picframe_test/delete_current_left/press")
    send(client, "picframe/picframe_test/delete_right/press")
    send(client, "picframe/picframe_test/delete_both/press")

    assert publisher.events[-3:] == [
        CommandEvent(command=Command.DELETE, payload={"target": "left"}),
        CommandEvent(command=Command.DELETE, payload={"target": "right"}),
        CommandEvent(command=Command.DELETE, payload={"target": "both"}),
    ]


def test_mqtt_rejects_right_or_both_delete_for_single_media() -> None:
    adapter, publisher, _subscriber, _state = build_adapter()
    client = connect_adapter(adapter)

    send(client, "picframe/picframe_test/delete_right/press")
    send(client, "picframe/picframe_test/delete_both/press")

    assert all(
        not (isinstance(event, CommandEvent) and event.command == Command.DELETE)
        for event in publisher.events
    )


def test_media_and_state_events_publish_mqtt_state() -> None:
    adapter, _publisher, subscriber, _state = build_adapter(
        FakeConfigRepository({"model.image_attr": ["EXIF FNumber"]})
    )
    client = connect_adapter(adapter)

    media_callback = subscriber.callbacks[CurrentMediaChangedEvent][0]
    state_callback = subscriber.callbacks[StateEvent][0]

    media_callback(
        CurrentMediaChangedEvent(
            media_item={
                "filepath": "/photos/a.jpg",
                "id": 7,
                "title": "Beach",
                "latitude": 51.5,
                "longitude": 7.4,
                "location": "Dortmund, Germany",
            }
        )
    )
    state_callback(StateEvent(state=State.PAUSED))

    published = {topic: payload for topic, payload, _qos, _retain in client.published}
    assert json.loads(published["picframe/picframe_test/media/state"]) == {
        "filename": "a.jpg",
        "layout": "single",
        "id": 7,
    }
    assert json.loads(published["picframe/picframe_test/media/attributes"]) == {
        "filepath": "/photos/a.jpg",
        "id": 7,
        "title": "Beach",
        "latitude": 51.5,
        "longitude": 7.4,
        "location": "Dortmund, Germany",
    }
    assert json.loads(published["picframe/picframe_test/state"])["state"] == "PAUSED"


def test_stop_unsubscribes_and_disconnects() -> None:
    adapter, _publisher, subscriber, _state = build_adapter()
    client = connect_adapter(adapter)

    adapter.stop()

    assert client.loop_stopped is True
    assert client.disconnected is True
    assert len(subscriber.unsubscribed) == 2
