"""
Wake-on-Input Service (#762).

Turns raw mouse/keyboard wake events from a backend input-device listener
(:class:`~picframe.core.ports.IWakeInputListener`) into ``Command.DISPLAY_ON``
events on the event bus. The listener reads input devices *independent of any
Wayland surface*, so it works while the configured output is destroyed by
``wlr-randr --off`` (the overlay's JS listeners cannot fire in that state).

The service is gated by the overlay's ``enabled_input_types`` list (mouse and
keyboard are wake-capable; touch is never a wake class) and by the current
display-power state (idempotent — it never wakes an already-on display). It
applies a short cooldown debounce to avoid publishing a storm of wake events
while the display is still transitioning on. It deliberately publishes only
``DISPLAY_ON``; the ``PLAY`` side-effect is owned by ``DisplayPowerManager``.
"""

import logging
import threading
import time
from typing import Any

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.ports import IDisplayPower, IWakeInputListener
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)

# Input classes that are eligible to wake the display. Touch is excluded by
# design: the overlay surface is destroyed while the output is off, so touch
# listeners cannot fire anyway, and touch-on-a-dark-screen is not a wake gesture.
WAKE_INPUT_CLASSES: frozenset[str] = frozenset({"mouse", "keyboard"})

# Default ``overlay.enabled_input_types`` value used when the key is absent.
_DEFAULT_ENABLED_INPUT_TYPES: list[str] = ["touch", "mouse", "keyboard"]

# Minimum time between published wake events while the display is still off.
# ``DisplayPowerManager`` already idempotently ignores duplicate ``DISPLAY_ON``
# commands once ``is_on()`` returns True; this just avoids a burst of redundant
# publishes during the brief turn-on transition.
_WAKE_COOLDOWN_SECONDS: float = 1.0


class WakeOnInputService:
    """
    Service that wakes the display on raw mouse-move / keypress events.

    Subscribes to ``StateEvent`` (CONFIG_CHANGED) so it reloads the
    ``overlay.enabled_input_types`` list live when the user changes it from
    the web UI.
    """

    def __init__(
        self,
        event_publisher: IEventPublisher,
        wake_adapter: IWakeInputListener,
        display_power_adapter: IDisplayPower,
        config_repository: IConfigRepository | None = None,
        event_subscriber: IEventSubscriber | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._wake_adapter = wake_adapter
        self._display_power = display_power_adapter
        self._config_repository = config_repository
        self._event_subscriber = event_subscriber
        self._enabled_input_types: set[str] = set(_DEFAULT_ENABLED_INPUT_TYPES)
        self._last_wake_time: float = 0.0
        self._lock = threading.Lock()
        self._is_subscribed = False

        self._wake_adapter.register_callback(self._handle_wake_event)
        if self._event_subscriber:
            self._event_subscriber.subscribe(StateEvent, self._handle_state_event)
            self._is_subscribed = True
        logger.info("WakeOnInputService initialized.")

    def _handle_wake_event(self, input_class: str) -> None:
        """Callback from the wake adapter when a wake-capable input occurs."""
        if input_class not in WAKE_INPUT_CLASSES:
            return
        if input_class not in self._enabled_input_types:
            return
        if self._display_power.is_on():
            return
        with self._lock:
            now = time.monotonic()
            if now - self._last_wake_time < _WAKE_COOLDOWN_SECONDS:
                return
            self._last_wake_time = now
        logger.info("WakeOnInputService: waking display on %s input.", input_class)
        self._event_publisher.publish(CommandEvent(command=Command.DISPLAY_ON))

    def _handle_state_event(self, event: Any) -> None:
        """Reload the enabled-input-types set on live overlay config changes."""
        if not isinstance(event, StateEvent) or event.state != State.CONFIG_CHANGED:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])
        if "overlay" not in updated_sections:
            return
        self._reload_enabled_input_types()

    def _reload_enabled_input_types(self) -> None:
        if self._config_repository is None:
            return
        raw = self._config_repository.get_app_config(
            "overlay.enabled_input_types", _DEFAULT_ENABLED_INPUT_TYPES
        )
        if isinstance(raw, list):
            self._enabled_input_types = {str(x) for x in raw}
        else:
            self._enabled_input_types = set(_DEFAULT_ENABLED_INPUT_TYPES)

    def start(self) -> None:
        """Reload config and start the underlying wake input adapter."""
        logger.info("WakeOnInputService: starting.")
        self._reload_enabled_input_types()
        self._wake_adapter.start()

    def stop(self) -> None:
        """Stop the underlying adapter and unsubscribe from config events."""
        logger.info("WakeOnInputService: stopping.")
        self._wake_adapter.stop()
        if self._event_subscriber and self._is_subscribed:
            self._event_subscriber.unsubscribe(StateEvent, self._handle_state_event)
            self._is_subscribed = False
