"""
Mock implementations of the Hardware Abstraction Layer (HAL) ports.

These adapters are used for development and testing on non-target hardware
(e.g., macOS, Windows, or headless CI environments) where physical GPIO
or specific display servers (like Wayland) are unavailable.
"""

import logging
from collections.abc import Callable
from typing import Any

from picframe.core.ports import IDisplayPower, IHardwareInput, ISystemManager

logger = logging.getLogger(__name__)


class MockDisplayPower(IDisplayPower):
    """Mock implementation of IDisplayPower."""

    def __init__(self) -> None:
        """Initialize the mock display power state."""
        self._is_on = True
        logger.info("MockDisplayPower initialized.")

    def turn_on(self) -> None:
        """Simulate turning the display on."""
        self._is_on = True
        logger.info("MockDisplayPower: Display turned ON.")

    def turn_off(self) -> None:
        """Simulate turning the display off."""
        self._is_on = False
        logger.info("MockDisplayPower: Display turned OFF.")

    def toggle(self) -> None:
        """Simulate toggling the display power state."""
        self._is_on = not self._is_on
        state = "ON" if self._is_on else "OFF"
        logger.info(f"MockDisplayPower: Display toggled {state}.")

    def set_brightness(self, value: float) -> None:
        """Simulate setting the display brightness."""
        logger.info(f"MockDisplayPower: Brightness set to {value:.2f}.")

    def is_on(self) -> bool:
        """
        Check the simulated display power state.

        Returns:
            bool: True if the simulated display is on, False otherwise.
        """
        return self._is_on

    def set_display_output(self, display_output: str) -> None:
        """Accept display-output retargeting for parity with real adapters."""
        logger.info(f"MockDisplayPower: Display output set to {display_output}.")


class MockHardwareInput(IHardwareInput):
    """Mock implementation of IHardwareInput."""

    def __init__(self) -> None:
        """Initialize the mock hardware input."""
        self._is_running = False
        self._callback: Callable[[str, str], None] | None = None
        self.config: dict[str, dict[str, Any]] = {}
        logger.info("MockHardwareInput initialized.")

    def register_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for simulated hardware events."""
        self._callback = callback
        logger.info("MockHardwareInput: Callback registered.")

    def configure(self, config: dict[str, dict[str, Any]]) -> None:
        """Store simulated hardware input configuration."""
        self.config = config
        logger.info("MockHardwareInput: Configuration updated.")

    def start(self) -> None:
        """Simulate starting hardware input monitoring."""
        self._is_running = True
        logger.info("MockHardwareInput: Monitoring started.")

    def stop(self) -> None:
        """Simulate stopping hardware input monitoring."""
        self._is_running = False
        logger.info("MockHardwareInput: Monitoring stopped.")

    def simulate_event(self, input_id: str, action: str) -> None:
        """
        Simulate a hardware event.

        Args:
            input_id: The ID of the simulated input (e.g., 'button_1').
            action: The simulated action (e.g., 'pressed').
        """
        if self._is_running and self._callback:
            logger.info(f"MockHardwareInput: Simulating event {input_id} -> {action}")
            self._callback(input_id, action)
        elif not self._is_running:
            logger.warning("MockHardwareInput: Cannot simulate event, monitoring is stopped.")
        else:
            logger.warning("MockHardwareInput: Cannot simulate event, no callback registered.")


class MockSystemManager(ISystemManager):
    """Mock implementation of ISystemManager."""

    def __init__(self) -> None:
        """Initialize the mock system manager."""
        logger.info("MockSystemManager initialized.")

    def reboot(self) -> None:
        """Simulate a system reboot."""
        logger.warning("MockSystemManager: System reboot requested (simulated).")

    def shutdown(self) -> None:
        """Simulate a system shutdown."""
        logger.warning("MockSystemManager: System shutdown requested (simulated).")
