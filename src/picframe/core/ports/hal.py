"""
Hardware Abstraction Layer (HAL) Ports.

This module defines the interfaces (ports) for interacting with the underlying
operating system and hardware. These interfaces ensure the core application
logic remains decoupled from specific OS implementations (e.g., Wayland, X11, macOS).
"""

from collections.abc import Callable
from typing import Any, Protocol


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

    def set_brightness(self, value: float) -> None:
        """
        Set the display brightness.

        Args:
            value: Brightness level between 0.0 and 1.0.
        """
        ...

    def is_on(self) -> bool:
        """
        Check if the display is currently on.

        Returns:
            bool: True if the display is on, False otherwise.
        """
        ...

    def set_display_output(self, display_output: str) -> None:
        """Update the display output targeted by power commands."""
        ...


class IHardwareInput(Protocol):
    """
    Interface for monitoring hardware inputs (e.g., GPIO pins, buttons, PIR sensors).
    """

    def register_callback(self, callback: Callable[[str, str], None]) -> None:
        """
        Register a callback to be invoked when a hardware event occurs.

        Args:
            callback: A function taking (input_id: str, action: str).
                      e.g., callback("next_button", "pressed")
        """
        ...

    def configure(self, config: dict[str, dict[str, Any]]) -> None:
        """Configure monitored inputs."""
        ...

    def start(self) -> None:
        """Start monitoring hardware inputs."""
        ...

    def stop(self) -> None:
        """Stop monitoring hardware inputs."""
        ...


class IWakeInputListener(Protocol):
    """
    Interface for a backend hardware-input listener that wakes the display.

    Unlike ``IHardwareInput`` (which maps user-configured GPIO/PIR inputs to
    commands), this listener is purpose-built to wake the display from the
    "off" state on raw mouse-move / keypress events. It reads input devices
    *independent of any Wayland surface* so it works while the configured
    output is destroyed by ``wlr-randr --off`` (#762).

    The registered callback receives an input-class string ("mouse" or
    "keyboard"); the owning service applies gating and debounce and publishes
    the actual ``CommandEvent``.
    """

    def register_callback(self, callback: Callable[[str], None]) -> None:
        """
        Register a callback invoked when a wake-capable input event occurs.

        Args:
            callback: A function taking an input-class string
                      ("mouse" or "keyboard").
        """
        ...

    def start(self) -> None:
        """Start listening for wake-capable input events."""
        ...

    def stop(self) -> None:
        """Stop listening and release input-device resources."""
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

    def picframe_service_status(self) -> str:
        """Return active, inactive, or unavailable for picframe.service."""
        ...

    def restart_picframe_service(self) -> bool:
        """Restart picframe.service if it is currently active."""
        ...
