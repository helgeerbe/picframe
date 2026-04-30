"""
Linux System Manager Adapter.

This module provides the `LinuxSystemManager` class, which implements
the `ISystemManager` interface for Linux-based systems (like Raspberry Pi OS).
It uses `subprocess` to execute system-level commands.
"""

import logging
import subprocess

from picframe.core.ports import ISystemManager

logger = logging.getLogger(__name__)


class LinuxSystemManager(ISystemManager):
    """
    Implementation of ISystemManager for Linux systems.
    """

    def __init__(self) -> None:
        """Initialize the LinuxSystemManager."""
        logger.info("LinuxSystemManager initialized.")

    def reboot(self) -> None:
        """
        Reboot the host system.
        Requires appropriate sudo/polkit permissions for the user running the app.
        """
        logger.warning("LinuxSystemManager: Executing system reboot.")
        try:
            subprocess.run(["sudo", "reboot"], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"LinuxSystemManager: Failed to execute reboot: {e}")
        except FileNotFoundError:
            logger.error("LinuxSystemManager: 'sudo' or 'reboot' command not found.")

    def shutdown(self) -> None:
        """
        Shut down the host system.
        Requires appropriate sudo/polkit permissions for the user running the app.
        """
        logger.warning("LinuxSystemManager: Executing system shutdown.")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"LinuxSystemManager: Failed to execute shutdown: {e}")
        except FileNotFoundError:
            logger.error("LinuxSystemManager: 'sudo' or 'shutdown' command not found.")
