"""
Hardware Abstraction Layer (HAL) Factory.

This module provides the factory logic to detect the host operating system
and instantiate the correct concrete adapters for the HAL ports.
"""

import logging
import os
import sys
from dataclasses import dataclass

from picframe.core.ports import IDisplayPower, IHardwareInput, ISystemManager
from picframe.infrastructure.os.mock_adapters import (
    MockDisplayPower,
    MockHardwareInput,
    MockSystemManager,
)
from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager
from picframe.infrastructure.os.wayland_power import WaylandDisplayPower

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HALAdapters:
    """
    Container for the instantiated HAL adapters.
    """

    display_power: IDisplayPower
    hardware_input: IHardwareInput
    system_manager: ISystemManager


class HALFactory:
    """
    Factory for creating OS-specific Hardware Abstraction Layer adapters.
    """

    @staticmethod
    def create_adapters(display_output: str = "HDMI-A-1") -> HALAdapters:
        """
        Detect the host OS and instantiate the appropriate HAL adapters.

        Args:
            display_output: The name of the display output (e.g., 'HDMI-A-1')
                            to be used by the display power adapter.

        Returns:
            HALAdapters: A container holding the concrete implementations
                         for the current operating system.
        """
        os_name = getattr(os, "name", "unknown")
        platform = sys.platform

        logger.info(f"HALFactory: Detecting OS... os.name='{os_name}', sys.platform='{platform}'")

        # TODO: Implement actual OS detection logic for Raspberry Pi (Wayland)
        # and Ubuntu VM once the concrete adapters are built in subsequent tasks.
        # For now, we default to the Mock adapters to ensure the application
        # can run cross-platform during Phase 2 development.

        if platform == "darwin" or platform == "win32":
            logger.info("HALFactory: Non-target OS detected. Injecting Mock Adapters.")
            return HALAdapters(
                display_power=MockDisplayPower(),
                hardware_input=MockHardwareInput(),
                system_manager=MockSystemManager(),
            )

        # Default fallback (e.g., Linux/Ubuntu VM during development or Raspberry Pi Wayland)
        # We inject WaylandDisplayPower here as it's the target environment.
        # If wlr-randr is missing (e.g., on a generic Ubuntu VM), the adapter
        # will log an error but won't crash the application.
        logger.info("HALFactory: Defaulting to Wayland/Mock Adapters for Linux.")
        return HALAdapters(
            display_power=WaylandDisplayPower(display_output=display_output),
            hardware_input=MockHardwareInput(),
            system_manager=LinuxSystemManager(),
        )
