"""
Hardware Abstraction Layer (HAL) Ports.

This module defines the interfaces (ports) for interacting with the underlying
operating system and hardware. These interfaces ensure the core application
logic remains decoupled from specific OS implementations (e.g., Wayland, X11, macOS).
"""

from typing import Protocol


class IDisplayPower(Protocol):
    """
    Interface for managing the physical display power state.
    """

    def turn_on(self) -> None:
        """Turn the display on."""
        ...

    def turn_off(self) -> None:
        """Turn the display off."""
        ...

    def toggle(self) -> None:
        """Toggle the display power state."""
        ...

    def is_on(self) -> bool:
        """
        Check if the display is currently on.

        Returns:
            bool: True if the display is on, False otherwise.
        """
        ...


class IHardwareInput(Protocol):
    """
    Interface for monitoring hardware inputs (e.g., GPIO pins, buttons, PIR sensors).
    """

    def start(self) -> None:
        """Start monitoring hardware inputs."""
        ...

    def stop(self) -> None:
        """Stop monitoring hardware inputs."""
        ...


class ISystemManager(Protocol):
    """
    Interface for executing system-level commands.
    """

    def reboot(self) -> None:
        """Reboot the host system."""
        ...

    def shutdown(self) -> None:
        """Shut down the host system."""
        ...
