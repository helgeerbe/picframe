"""
Raspberry Pi GPIO Adapter.

This module provides the `RPiGPIOAdapter`, which implements the `IHardwareInput`
port using the `gpiozero` library. It supports buttons and PIR motion sensors.
"""

import logging
from collections.abc import Callable
from typing import Any

from gpiozero import Button, MotionSensor

from picframe.core.ports import IHardwareInput

logger = logging.getLogger(__name__)


class RPiGPIOAdapter(IHardwareInput):
    """
    Adapter for monitoring Raspberry Pi GPIO pins using gpiozero.
    """

    def __init__(self, config: dict[str, dict[str, Any]]) -> None:
        """
        Initialize the RPiGPIOAdapter.

        Args:
            config: A dictionary defining the hardware inputs.
                    Format: { "input_id": { "type": "button|pir", "pin": int, ... } }
        """
        self._config = config
        self._callback: Callable[[str, str], None] | None = None
        self._devices: list[Any] = []
        self._is_running = False
        logger.info("RPiGPIOAdapter initialized.")

    def register_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for hardware events."""
        self._callback = callback
        logger.info("RPiGPIOAdapter: Callback registered.")

    def configure(self, config: dict[str, dict[str, Any]]) -> None:
        """Replace GPIO input configuration."""
        was_running = self._is_running
        if was_running:
            self.stop()
        self._config = config
        logger.info("RPiGPIOAdapter: Configuration updated.")
        if was_running:
            self.start()

    def _notify(self, input_id: str, action: str) -> None:
        """Internal method to invoke the registered callback."""
        if self._callback and self._is_running:
            self._callback(input_id, action)

    def start(self) -> None:
        """
        Start monitoring hardware inputs.
        Instantiates gpiozero devices based on the configuration.
        """
        if self._is_running:
            logger.warning("RPiGPIOAdapter is already running.")
            return

        self._is_running = True
        logger.info("RPiGPIOAdapter: Starting hardware monitoring.")

        for input_id, settings in self._config.items():
            device_type = settings.get("type")
            pin = settings.get("pin")

            if not device_type or pin is None:
                logger.error(
                    f"RPiGPIOAdapter: Invalid config for '{input_id}'. Missing type or pin."
                )
                continue

            try:
                if device_type == "button":
                    bounce_time = settings.get("bounce_time", 0.1)
                    btn = Button(pin, bounce_time=bounce_time)
                    # Use default arguments in lambda to capture the current input_id
                    btn.when_pressed = lambda id=input_id: self._notify(id, "pressed")
                    btn.when_released = lambda id=input_id: self._notify(id, "released")
                    self._devices.append(btn)
                    logger.info(f"RPiGPIOAdapter: Configured Button '{input_id}' on pin {pin}")

                elif device_type == "pir":
                    pir = MotionSensor(pin)
                    pir.when_motion = lambda id=input_id: self._notify(id, "motion_detected")
                    pir.when_no_motion = lambda id=input_id: self._notify(id, "no_motion")
                    self._devices.append(pir)
                    logger.info(f"RPiGPIOAdapter: Configured PIR '{input_id}' on pin {pin}")

                else:
                    logger.warning(
                        f"RPiGPIOAdapter: Unknown device type '{device_type}' for '{input_id}'"
                    )

            except Exception as e:
                logger.error(f"RPiGPIOAdapter: Failed to configure '{input_id}' on pin {pin}: {e}")

    def stop(self) -> None:
        """
        Stop monitoring hardware inputs and release GPIO resources.
        """
        if not self._is_running:
            return

        logger.info("RPiGPIOAdapter: Stopping hardware monitoring and releasing resources.")
        self._is_running = False

        for device in self._devices:
            try:
                device.close()
            except Exception as e:
                logger.error(f"RPiGPIOAdapter: Error closing device: {e}")

        self._devices.clear()
