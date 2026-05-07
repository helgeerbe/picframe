"""
Wayland Display Power Adapter.

This module provides the concrete implementation of the IDisplayPower port
for Wayland environments, utilizing the `wlr-randr` utility to manage
display power states.
"""

import logging
import subprocess
from typing import Optional

from picframe.core.events.dto import SystemErrorEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.ports import IDisplayPower

logger = logging.getLogger(__name__)


class WaylandDisplayPower(IDisplayPower):
    """
    Concrete implementation of IDisplayPower for Wayland using wlr-randr.
    Uses ddcutil for external monitor brightness and brightnessctl for internal displays.
    """

    def __init__(self, display_output: str = "HDMI-A-1", is_external: bool = True, publisher: Optional[IEventPublisher] = None) -> None:
        """
        Initialize the Wayland display power adapter.

        Args:
            display_output: The name of the Wayland output to control (e.g., 'HDMI-A-1').
            is_external: Whether the display is external (uses ddcutil) or internal (uses brightnessctl).
            publisher: Optional event publisher for broadcasting system errors.
        """
        self._is_on = True
        self._display_output = display_output
        self.is_external = is_external
        self._publisher = publisher
        logger.info(f"WaylandDisplayPower initialized for output: {self._display_output}, external: {self.is_external}")

    def turn_on(self) -> None:
        """Turn the display on using wlr-randr."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", self._display_output, "--on"],
                check=True,
                capture_output=True,
            )
            self._is_on = True
            logger.info(f"WaylandDisplayPower: Display {self._display_output} turned ON.")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to turn display ON: {e.stderr.decode()}"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))
        except FileNotFoundError:
            error_msg = "wlr-randr not found. Is it installed?"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))

    def turn_off(self) -> None:
        """Turn the display off using wlr-randr."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", self._display_output, "--off"],
                check=True,
                capture_output=True,
            )
            self._is_on = False
            logger.info("WaylandDisplayPower: Display turned OFF.")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to turn display OFF: {e.stderr.decode()}"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))
        except FileNotFoundError:
            error_msg = "wlr-randr not found. Is it installed?"
            logger.error(f"WaylandDisplayPower: {error_msg}")
            if self._publisher:
                self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))

    def toggle(self) -> None:
        """Toggle the display power state."""
        if self.is_on():
            self.turn_off()
        else:
            self.turn_on()

    def set_brightness(self, value: float) -> None:
        """Set the display brightness (0.0 to 1.0)."""
        percent_int = max(0, min(100, int(value * 100)))
        
        if self.is_external:
            # Use ddcutil for HDMI/DP monitors
            try:
                subprocess.run(
                    ["ddcutil", "setvcp", "10", str(percent_int)],
                    check=True, capture_output=True, timeout=5.0
                )
                logger.info(f"Set external monitor brightness to {percent_int}%")
            except Exception as e:
                error_msg = f"Failed to set external brightness via ddcutil: {e}"
                logger.error(error_msg)
                if self._publisher:
                    self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))
        else:
            # Use brightnessctl for internal/DSI displays
            try:
                subprocess.run(
                    ["brightnessctl", "set", f"{percent_int}%"],
                    check=True, capture_output=True
                )
                logger.info(f"Set internal display brightness to {percent_int}%")
            except Exception as e:
                error_msg = f"Failed to set internal brightness via brightnessctl: {e}"
                logger.error(error_msg)
                if self._publisher:
                    self._publisher.publish(SystemErrorEvent(component="WaylandDisplayPower", message=error_msg))

    def is_on(self) -> bool:
        """
        Check if the display is currently on.

        Returns:
            bool: True if the display is on, False otherwise.
        """
        return self._is_on
