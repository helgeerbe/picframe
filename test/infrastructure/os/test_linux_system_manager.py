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


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_picframe_service_status_reports_active(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/bin/systemctl"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["systemctl", "is-active"],
        returncode=0,
    )

    status = LinuxSystemManager().picframe_service_status()

    assert status == "active"
    mock_run.assert_called_once_with(
        ["/usr/bin/systemctl", "is-active", "--quiet", "picframe.service"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_picframe_service_status_reports_inactive(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/bin/systemctl"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["systemctl", "is-active"],
        returncode=3,
    )

    assert LinuxSystemManager().picframe_service_status() == "inactive"


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_picframe_service_status_reports_unavailable_without_systemctl(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = None

    assert LinuxSystemManager().picframe_service_status() == "unavailable"
    mock_run.assert_not_called()


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_restart_picframe_service_uses_noninteractive_sudo_when_active(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/bin/systemctl"
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=["systemctl", "is-active"], returncode=0),
        subprocess.CompletedProcess(args=["sudo", "systemctl", "restart"], returncode=0),
    ]

    assert LinuxSystemManager().restart_picframe_service() is True

    assert mock_run.call_args_list[1].args[0] == [
        "sudo",
        "-n",
        "/usr/bin/systemctl",
        "restart",
        "picframe.service",
    ]
    assert mock_run.call_args_list[1].kwargs == {
        "check": True,
        "capture_output": True,
        "text": True,
    }


@patch("picframe.infrastructure.os.linux_system_manager.subprocess.run")
@patch("picframe.infrastructure.os.linux_system_manager.shutil.which")
def test_restart_picframe_service_returns_false_when_inactive(
    mock_which: Any,
    mock_run: Any,
) -> None:
    mock_which.return_value = "/usr/bin/systemctl"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["systemctl", "is-active"],
        returncode=3,
    )

    assert LinuxSystemManager().restart_picframe_service() is False
    assert mock_run.call_count == 1
