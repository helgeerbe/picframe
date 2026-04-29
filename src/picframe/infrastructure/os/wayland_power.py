"""
Wayland Display Power Adapter.

This module provides the concrete implementation of the IDisplayPower port
for Wayland environments, utilizing the `wlr-randr` utility to manage
display power states.
"""

import logging
import subprocess

from picframe.core.ports import IDisplayPower

logger = logging.getLogger(__name__)


class WaylandDisplayPower(IDisplayPower):
    """
    Concrete implementation of IDisplayPower for Wayland using wlr-randr.
    """

    def __init__(self, display_output: str = "HDMI-A-1") -> None:
        """
        Initialize the Wayland display power adapter.

        Args:
            display_output: The name of the Wayland output to control (e.g., 'HDMI-A-1').
        """
        self._is_on = True
        self._display_output = display_output
        logger.info(f"WaylandDisplayPower initialized for output: {self._display_output}")

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
            logger.error(f"WaylandDisplayPower: Failed to turn display ON: {e.stderr.decode()}")
        except FileNotFoundError:
            logger.error("WaylandDisplayPower: wlr-randr not found. Is it installed?")

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
            logger.error(f"WaylandDisplayPower: Failed to turn display OFF: {e.stderr.decode()}")
        except FileNotFoundError:
            logger.error("WaylandDisplayPower: wlr-randr not found. Is it installed?")

    def toggle(self) -> None:
        """Toggle the display power state."""
        if self.is_on():
            self.turn_off()
        else:
            self.turn_on()

    def is_on(self) -> bool:
        """
        Check if the display is currently on.

        Returns:
            bool: True if the display is on, False otherwise.
        """
        return self._is_on
