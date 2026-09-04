"""
Hardware Input Service.

This module provides the `HardwareInputService`, which listens for hardware
events (like button presses or PIR sensor triggers) from the injected
Hardware Abstraction Layer (HAL) adapter and translates them into
`CommandEvent`s published to the Event Bus.
"""

import logging
import threading
from typing import Any

from picframe.core.events.dto import Command, CommandEvent, State, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.models.hardware_input import (
    HardwareInputConfigError,
    derive_hardware_input_runtime_config,
    hardware_inputs_from_flat_config,
)
from picframe.core.ports import IHardwareInput
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)


class HardwareInputService:
    """
    Service responsible for translating hardware inputs into system commands.
    """

    def __init__(
        self,
        event_bus: IEventPublisher,
        hardware_input_adapter: IHardwareInput,
        input_mapping: dict[str, dict[str, str]] | None = None,
        config_repository: IConfigRepository | None = None,
        event_subscriber: IEventSubscriber | None = None,
    ) -> None:
        """
        Initialize the HardwareInputService.

        Args:
            event_bus: The event bus publisher interface.
            hardware_input_adapter: The injected HAL adapter for hardware inputs.
            input_mapping: Optional static mapping from input IDs and actions to commands.
                           Format: { "input_id": { "action": "COMMAND_NAME" } }
                           Example: { "next_button": { "pressed": "NEXT" } }
            config_repository: Optional repository for runtime hardware_inputs config.
            event_subscriber: Optional subscriber used to react to config changes.
        """
        self._event_bus = event_bus
        self._adapter = hardware_input_adapter
        self._mapping = input_mapping or {}
        self._no_motion_delays: dict[str, float] = {}
        self._no_motion_timers: dict[str, threading.Timer] = {}
        self._timer_lock = threading.RLock()
        self._config_repository = config_repository
        self._event_subscriber = event_subscriber
        self._is_running = False
        self._is_subscribed = False

        # Register the callback with the adapter
        self._adapter.register_callback(self._handle_hardware_event)
        if self._event_subscriber:
            self._event_subscriber.subscribe(StateEvent, self._handle_state_event)
            self._is_subscribed = True
        logger.info("HardwareInputService initialized.")

    def _handle_hardware_event(self, input_id: str, action: str) -> None:
        """
        Callback invoked by the HAL adapter when a hardware event occurs.

        Args:
            input_id: The ID of the hardware input (e.g., 'next_button').
            action: The action that occurred (e.g., 'pressed', 'motion_detected').
        """
        logger.debug(f"HardwareInputService: Received event {input_id} -> {action}")

        if action == "motion_detected":
            self._cancel_no_motion_timer(input_id)
            self._publish_mapped_command(input_id, action)
            return

        if action == "no_motion":
            with self._timer_lock:
                delay_seconds = self._no_motion_delays.get(input_id, 0.0)
            if delay_seconds > 0:
                self._schedule_no_motion_command(input_id, action, delay_seconds)
                return

        self._publish_mapped_command(input_id, action)

    def _publish_mapped_command(self, input_id: str, action: str) -> None:
        command_name = self._resolve_command_name(input_id, action)
        if not command_name:
            return

        self._publish_command_name(input_id, action, command_name)

    def _resolve_command_name(self, input_id: str, action: str) -> str | None:
        with self._timer_lock:
            device_mapping = self._mapping.get(input_id)
        if not device_mapping:
            logger.warning(f"HardwareInputService: No mapping found for input '{input_id}'")
            return None

        command_name = device_mapping.get(action)
        if not command_name:
            logger.warning(
                "HardwareInputService: No command mapped for action "
                f"'{action}' on input '{input_id}'"
            )
            return None

        return command_name

    def _publish_command_name(self, input_id: str, action: str, command_name: str) -> None:
        try:
            command = Command[command_name]
            logger.info(f"HardwareInputService: Translating {input_id}:{action} to {command.name}")
            self._event_bus.publish(CommandEvent(command=command))
        except KeyError:
            logger.error(f"HardwareInputService: Invalid command name '{command_name}' in mapping.")

    def _schedule_no_motion_command(self, input_id: str, action: str, delay_seconds: float) -> None:
        command_name = self._resolve_command_name(input_id, action)
        if not command_name:
            return

        with self._timer_lock:
            existing_timer = self._no_motion_timers.pop(input_id, None)
            timer = threading.Timer(
                delay_seconds,
                self._publish_delayed_no_motion_command,
                args=(input_id, action, command_name),
            )
            timer.daemon = True
            self._no_motion_timers[input_id] = timer

        if existing_timer:
            existing_timer.cancel()
        timer.start()
        logger.info(
            "HardwareInputService: Scheduled %s:%s as %s after %.1fs",
            input_id,
            action,
            command_name,
            delay_seconds,
        )

    def _publish_delayed_no_motion_command(
        self,
        input_id: str,
        action: str,
        command_name: str,
    ) -> None:
        with self._timer_lock:
            self._no_motion_timers.pop(input_id, None)
        self._publish_command_name(input_id, action, command_name)

    def _cancel_no_motion_timer(self, input_id: str) -> None:
        with self._timer_lock:
            timer = self._no_motion_timers.pop(input_id, None)
        if timer:
            timer.cancel()
            logger.info(
                "HardwareInputService: Cancelled pending no-motion command for %s",
                input_id,
            )

    def _cancel_all_no_motion_timers(self) -> None:
        with self._timer_lock:
            timers = list(self._no_motion_timers.values())
            self._no_motion_timers.clear()
        for timer in timers:
            timer.cancel()

    def _schedule_initial_no_motion_commands(self) -> None:
        with self._timer_lock:
            scheduled_inputs = [
                (input_id, delay_seconds)
                for input_id, delay_seconds in self._no_motion_delays.items()
                if self._mapping.get(input_id, {}).get("no_motion")
            ]

        for input_id, delay_seconds in scheduled_inputs:
            self._schedule_no_motion_command(input_id, "no_motion", delay_seconds)

    def start(self) -> None:
        """Start the underlying hardware input adapter."""
        logger.info("HardwareInputService: Starting hardware monitoring.")
        self._is_running = True
        if self._config_repository:
            self._reload_from_repository()
        else:
            self._adapter.start()

    def stop(self) -> None:
        """Stop the underlying hardware input adapter."""
        logger.info("HardwareInputService: Stopping hardware monitoring.")
        self._is_running = False
        self._cancel_all_no_motion_timers()
        self._adapter.stop()
        if self._event_subscriber and self._is_subscribed:
            self._event_subscriber.unsubscribe(StateEvent, self._handle_state_event)
            self._is_subscribed = False

    def _handle_state_event(self, event: Any) -> None:
        if not isinstance(event, StateEvent) or event.state != State.CONFIG_CHANGED:
            return

        payload = event.payload if isinstance(event.payload, dict) else {}
        updated_sections = payload.get("updated_sections", [])
        if "hardware_inputs" in updated_sections:
            self._reload_from_repository()

    def _reload_from_repository(self) -> None:
        if not self._config_repository:
            return

        try:
            flat_config = self._config_repository.get_all_app_config()
            config = hardware_inputs_from_flat_config(flat_config)
            enabled, adapter_config, command_mapping, no_motion_delays = (
                derive_hardware_input_runtime_config(config)
            )
        except HardwareInputConfigError as e:
            logger.error(f"HardwareInputService: Invalid hardware input config: {e}")
            with self._timer_lock:
                self._mapping = {}
                self._no_motion_delays = {}
            self._cancel_all_no_motion_timers()
            self._adapter.stop()
            return

        self._cancel_all_no_motion_timers()
        self._adapter.stop()
        with self._timer_lock:
            self._mapping = command_mapping
            self._no_motion_delays = no_motion_delays
        self._adapter.configure(adapter_config)

        if self._is_running and enabled:
            self._adapter.start()
            self._schedule_initial_no_motion_commands()
            logger.info("HardwareInputService: Hardware inputs enabled.")
        else:
            logger.info("HardwareInputService: Hardware inputs disabled.")
