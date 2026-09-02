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
SYSTEMCTL_FALLBACK_PATHS = ("/usr/bin/systemctl", "/bin/systemctl")
PICFRAME_SERVICE_NAME = "picframe.service"


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

    def picframe_service_status(self) -> str:
        """Return active, inactive, or unavailable for picframe.service."""
        systemctl_path = shutil.which("systemctl")
        if not systemctl_path:
            return "unavailable"
        try:
            result = subprocess.run(
                [systemctl_path, "is-active", "--quiet", PICFRAME_SERVICE_NAME],
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("LinuxSystemManager: Could not inspect picframe.service: %s", exc)
            return "unavailable"
        return "active" if result.returncode == 0 else "inactive"

    def restart_picframe_service(self) -> bool:
        """Restart picframe.service when it is known to be active."""
        if self.picframe_service_status() != "active":
            return False
        systemctl_path = _resolve_command("systemctl", SYSTEMCTL_FALLBACK_PATHS)
        logger.warning("LinuxSystemManager: Restarting %s.", PICFRAME_SERVICE_NAME)
        try:
            subprocess.run(
                ["sudo", "-n", systemctl_path, "restart", PICFRAME_SERVICE_NAME],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            logger.error(
                "LinuxSystemManager: Failed to restart %s. Passwordless sudo may be missing%s",
                PICFRAME_SERVICE_NAME,
                detail,
            )
        except FileNotFoundError:
            logger.error("LinuxSystemManager: 'sudo' or '%s' command not found.", systemctl_path)
        return False

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
                "LinuxSystemManager: Failed to execute %s. Passwordless sudo may be missing%s",
                action,
                detail,
            )
        except FileNotFoundError:
            logger.error(
                "LinuxSystemManager: 'sudo' or '%s' command not found.",
                command[0],
            )
