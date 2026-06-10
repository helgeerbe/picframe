"""Tests for Linux system power management."""

import logging
import subprocess
from typing import Any
from unittest.mock import patch

from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_reboot_uses_noninteractive_sudo_with_absolute_path(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/sbin/reboot"

    LinuxSystemManager().reboot()

    mock_which.assert_called_once_with("reboot")
    mock_run.assert_called_once_with(
        ["sudo", "-n", "/usr/sbin/reboot"],
        check=True,
        capture_output=True,
        text=True,
    )


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_shutdown_uses_noninteractive_sudo_with_exact_arguments(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/sbin/shutdown"

    LinuxSystemManager().shutdown()

    mock_which.assert_called_once_with("shutdown")
    mock_run.assert_called_once_with(
        ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"],
        check=True,
        capture_output=True,
        text=True,
    )


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_reboot_uses_fallback_path_when_command_is_not_on_path(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = None

    LinuxSystemManager().reboot()

    mock_run.assert_called_once_with(
        ["sudo", "-n", "/usr/sbin/reboot"],
        check=True,
        capture_output=True,
        text=True,
    )


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_power_command_logs_permission_error_without_prompting(
    mock_which: Any,
    mock_run: Any,
    caplog: Any,
) -> None:
    mock_which.return_value = "/usr/sbin/reboot"
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["sudo", "-n", "/usr/sbin/reboot"],
        stderr="a password is required",
    )

    with caplog.at_level(logging.ERROR):
        LinuxSystemManager().reboot()

    assert "Passwordless sudo may be missing: a password is required" in caplog.text
