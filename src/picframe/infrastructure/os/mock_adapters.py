"""
Mock implementations of the Hardware Abstraction Layer (HAL) ports.

These adapters are used for development and testing on non-target hardware
(e.g., macOS, Windows, or headless CI environments) where physical GPIO
or specific display servers (like Wayland) are unavailable.
"""

import logging

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

    def is_on(self) -> bool:
        """
        Check the simulated display power state.

        Returns:
            bool: True if the simulated display is on, False otherwise.
        """
        return self._is_on


class MockHardwareInput(IHardwareInput):
    """Mock implementation of IHardwareInput."""

    def __init__(self) -> None:
        """Initialize the mock hardware input."""
        self._is_running = False
        logger.info("MockHardwareInput initialized.")

    def start(self) -> None:
        """Simulate starting hardware input monitoring."""
        self._is_running = True
        logger.info("MockHardwareInput: Monitoring started.")

    def stop(self) -> None:
        """Simulate stopping hardware input monitoring."""
        self._is_running = False
        logger.info("MockHardwareInput: Monitoring stopped.")


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
