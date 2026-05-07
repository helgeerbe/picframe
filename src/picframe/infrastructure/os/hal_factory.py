"""
Hardware Abstraction Layer (HAL) Factory.

This module provides the factory logic to detect the host operating system
and instantiate the correct concrete adapters for the HAL ports.
"""

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from picframe.core.ports import IDisplayPower, IHardwareInput, ISystemManager
from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager
from picframe.infrastructure.os.mock_adapters import (
    MockDisplayPower,
    MockHardwareInput,
    MockSystemManager,
)
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
    def _is_raspberry_pi() -> bool:
        try:
            with open("/proc/device-tree/model") as f:
                model = f.read().lower()
                return "raspberry pi" in model
        except (FileNotFoundError, PermissionError, OSError):
            return False

    @staticmethod
    def _is_wayland() -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY"))

    @staticmethod
    def _is_x11() -> bool:
        return bool(os.environ.get("DISPLAY")) and not HALFactory._is_wayland()

    @staticmethod
    def _has_wlr_randr() -> bool:
        return shutil.which("wlr-randr") is not None

    @staticmethod
    def create_adapters(
        display_output: str = "HDMI-A-1",
        hardware_input_config: dict[str, dict[str, Any]] | None = None
    ) -> HALAdapters:
        """
        Detect the host OS and instantiate the appropriate HAL adapters.

        Args:
            display_output: The name of the display output (e.g., 'HDMI-A-1')
                            to be used by the display power adapter.
            hardware_input_config: Configuration dictionary for hardware inputs.

        Returns:
            HALAdapters: A container holding the concrete implementations
                         for the current operating system.
        """
        os_name = getattr(os, "name", "unknown")
        platform = sys.platform

        logger.info(f"HALFactory: Detecting OS... os.name='{os_name}', sys.platform='{platform}'")

        if platform == "darwin" or platform == "win32":
            logger.info("HALFactory: Non-target OS detected. Injecting Mock Adapters.")
            return HALAdapters(
                display_power=MockDisplayPower(),
                hardware_input=MockHardwareInput(),
                system_manager=MockSystemManager(),
            )

        # Linux environment detection
        is_rpi = HALFactory._is_raspberry_pi()
        
        # Refined Display Server Detection
        xdg_session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        is_wayland = xdg_session_type == "wayland" or HALFactory._is_wayland()
        is_x11 = xdg_session_type == "x11" or HALFactory._is_x11()
        
        has_wlr_randr = HALFactory._has_wlr_randr()

        logger.info(
            f"HALFactory: Environment - RPi: {is_rpi}, Wayland: {is_wayland}, "
            f"X11: {is_x11}, wlr-randr: {has_wlr_randr}"
        )

        if is_x11:
            logger.warning(
                "HALFactory: X11 detected. X11 is not supported. Falling back to Mock Adapters."
            )
            return HALAdapters(
                display_power=MockDisplayPower(),
                hardware_input=MockHardwareInput(),
                system_manager=LinuxSystemManager(),
            )

        # Determine Display Power Adapter
        display_power: IDisplayPower
        if is_wayland and has_wlr_randr:
            logger.info(
                "HALFactory: Wayland and wlr-randr detected. Injecting WaylandDisplayPower."
            )
            display_power = WaylandDisplayPower(display_output=display_output)
        else:
            logger.info("HALFactory: Wayland or wlr-randr missing. Injecting MockDisplayPower.")
            display_power = MockDisplayPower()

        # Determine Hardware Input Adapter
        hardware_input: IHardwareInput
        if is_rpi and hardware_input_config is not None:
            logger.info("HALFactory: Raspberry Pi detected. Injecting RPiGPIOAdapter.")
            from picframe.infrastructure.os.rpi_gpio_adapter import RPiGPIOAdapter
            hardware_input = RPiGPIOAdapter(config=hardware_input_config)
        elif is_rpi:
            logger.warning(
                "HALFactory: Raspberry Pi detected, but no hardware_input_config provided. "
                "Injecting MockHardwareInput."
            )
            hardware_input = MockHardwareInput()
        else:
            logger.info("HALFactory: Generic Linux detected. Injecting MockHardwareInput.")
            hardware_input = MockHardwareInput()

        return HALAdapters(
            display_power=display_power,
            hardware_input=hardware_input,
            system_manager=LinuxSystemManager(),
        )
