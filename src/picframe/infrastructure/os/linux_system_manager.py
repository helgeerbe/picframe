"""
Linux System Manager Adapter.

This module provides the `LinuxSystemManager` class, which implements
the `ISystemManager` interface for Linux-based systems (like Raspberry Pi OS).
It uses `subprocess` to execute system-level commands.
"""

import logging
import shutil
import subprocess

from picframe.core.ports import ISystemManager

logger = logging.getLogger(__name__)

REBOOT_FALLBACK_PATHS = ("/usr/sbin/reboot", "/sbin/reboot")
SHUTDOWN_FALLBACK_PATHS = ("/usr/sbin/shutdown", "/sbin/shutdown")


def _resolve_command(name: str, fallback_paths: tuple[str, ...]) -> str:
    """Resolve a system command to the absolute path sudoers expects."""
    resolved = shutil.which(name)
    if resolved:
        return resolved
    return fallback_paths[0]


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
        reboot_path = _resolve_command("reboot", REBOOT_FALLBACK_PATHS)
        self._run_power_command("reboot", [reboot_path])

    def shutdown(self) -> None:
        """
        Shut down the host system.
        Requires appropriate sudo/polkit permissions for the user running the app.
        """
        shutdown_path = _resolve_command("shutdown", SHUTDOWN_FALLBACK_PATHS)
        self._run_power_command("shutdown", [shutdown_path, "-h", "now"])

    def _run_power_command(self, action: str, command: list[str]) -> None:
        logger.warning("LinuxSystemManager: Executing system %s.", action)
        try:
            subprocess.run(
                ["sudo", "-n", *command],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            logger.error(
                "LinuxSystemManager: Failed to execute %s. "
                "Passwordless sudo may be missing%s",
                action,
                detail,
            )
        except FileNotFoundError:
            logger.error(
                "LinuxSystemManager: 'sudo' or '%s' command not found.",
                command[0],
            )
