"""
Tests for the WaylandDisplayPower adapter.
"""

import subprocess
from typing import Any
from unittest.mock import MagicMock, call, patch

from picframe.core.events.dto import SystemErrorEvent
from picframe.infrastructure.os.wayland_power import WaylandDisplayPower


def test_wayland_power_initialization() -> None:
    """Test that the adapter initializes with the correct default output."""
    adapter = WaylandDisplayPower()
    assert adapter._display_output == "HDMI-A-1"
    assert adapter.is_on() is True

    adapter_custom = WaylandDisplayPower(display_output="DSI-1")
    assert adapter_custom._display_output == "DSI-1"
    assert adapter_custom.is_external is False


def test_wayland_power_can_retarget_display_output() -> None:
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    adapter.set_display_output("HDMI-A-2")

    assert adapter._display_output == "HDMI-A-2"


def test_wayland_power_retarget_infers_internal_display() -> None:
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    adapter.set_display_output("DSI-1")

    assert adapter._display_output == "DSI-1"
    assert adapter.is_external is False


@patch("subprocess.run")
def test_wayland_power_turn_on(mock_run: Any) -> None:
    """Test that turn_on executes the correct wlr-randr command."""
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")
    adapter._is_on = False  # Force state to off

    adapter.turn_on()

    mock_run.assert_called_once_with(
        ["wlr-randr", "--output", "HDMI-A-1", "--on"],
        check=True,
        capture_output=True,
    )
    assert adapter.is_on() is True


@patch("subprocess.run")
def test_wayland_power_turn_off(mock_run: Any) -> None:
    """Test that turn_off executes the correct wlr-randr command."""
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    adapter.turn_off()

    mock_run.assert_called_once_with(
        ["wlr-randr", "--output", "HDMI-A-1", "--off"],
        check=True,
        capture_output=True,
    )
    assert adapter.is_on() is False


@patch("subprocess.run")
def test_wayland_power_toggle(mock_run: Any) -> None:
    """Test that toggle switches the state and calls the correct command."""
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    # Initially ON, toggle should turn OFF
    adapter.toggle()
    mock_run.assert_called_with(
        ["wlr-randr", "--output", "HDMI-A-1", "--off"],
        check=True,
        capture_output=True,
    )
    assert adapter.is_on() is False

    # Now OFF, toggle should turn ON
    adapter.toggle()
    mock_run.assert_called_with(
        ["wlr-randr", "--output", "HDMI-A-1", "--on"],
        check=True,
        capture_output=True,
    )
    assert adapter.is_on() is True


@patch("subprocess.run")
def test_wayland_power_handles_subprocess_error(mock_run: Any) -> None:
    """Test that wlr-randr execution errors publish an event."""
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd="wlr-randr", stderr=b"Error"
    )
    mock_publisher = MagicMock()
    adapter = WaylandDisplayPower(publisher=mock_publisher)

    # Should not raise an exception
    adapter.turn_off()
    # State should remain unchanged if the command failed
    assert adapter.is_on() is True
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, SystemErrorEvent)
    assert event.component == "WaylandDisplayPower"
    assert "Failed to turn display OFF" in event.message


@patch("subprocess.run")
def test_wayland_power_handles_file_not_found(mock_run: Any) -> None:
    """Test that the adapter handles missing wlr-randr gracefully and publishes an event."""
    mock_run.side_effect = FileNotFoundError()
    mock_publisher = MagicMock()
    adapter = WaylandDisplayPower(publisher=mock_publisher)

    # Should not raise an exception
    adapter.turn_off()
    # State should remain unchanged if the command failed
    assert adapter.is_on() is True
    
    # Verify event was published
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args[0][0]
    assert isinstance(event, SystemErrorEvent)
    assert event.component == "WaylandDisplayPower"
    assert "wlr-randr not found" in event.message


@patch("subprocess.run")
def test_wayland_power_external_brightness_probes_ddc_once(mock_run: Any) -> None:
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    adapter.set_brightness(0.81)
    adapter.set_brightness(0.5)

    assert mock_run.call_args_list == [
        call(["ddcutil", "getvcp", "10"], check=True, capture_output=True, timeout=5.0),
        call(["ddcutil", "setvcp", "10", "81"], check=True, capture_output=True, timeout=5.0),
        call(["ddcutil", "setvcp", "10", "50"], check=True, capture_output=True, timeout=5.0),
    ]


@patch("subprocess.run")
def test_wayland_power_ddc_probe_failure_reports_command_output_once(
    mock_run: Any,
) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ddcutil", "getvcp", "10"],
        output=b"Display 1",
        stderr=b"DDC communication failed",
    )
    mock_publisher = MagicMock()
    adapter = WaylandDisplayPower(display_output="HDMI-A-1", publisher=mock_publisher)

    adapter.set_brightness(0.81)
    adapter.set_brightness(0.5)

    mock_run.assert_called_once_with(
        ["ddcutil", "getvcp", "10"],
        check=True,
        capture_output=True,
        timeout=5.0,
    )
    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args.args[0]
    assert isinstance(event, SystemErrorEvent)
    assert event.component == "WaylandDisplayPower"
    assert event.code == "brightness_unavailable"
    assert "cannot verify VCP 0x10" in event.message
    assert "DDC communication failed" in event.message
    assert "Display 1" in event.message


@patch("subprocess.run")
def test_wayland_power_external_brightness_failure_reports_stderr(
    mock_run: Any,
) -> None:
    mock_run.side_effect = [
        subprocess.CompletedProcess(["ddcutil", "getvcp", "10"], 0),
        subprocess.CalledProcessError(
            returncode=1,
            cmd=["ddcutil", "setvcp", "10", "81"],
            stderr=b"Value out of range",
        ),
    ]
    mock_publisher = MagicMock()
    adapter = WaylandDisplayPower(display_output="HDMI-A-1", publisher=mock_publisher)

    adapter.set_brightness(0.81)

    mock_publisher.publish.assert_called_once()
    event = mock_publisher.publish.call_args.args[0]
    assert isinstance(event, SystemErrorEvent)
    assert "Failed to set external brightness via ddcutil" in event.message
    assert "Value out of range" in event.message


@patch("subprocess.run")
def test_wayland_power_internal_brightness_uses_brightnessctl(mock_run: Any) -> None:
    adapter = WaylandDisplayPower(display_output="DSI-1")

    adapter.set_brightness(0.81)

    mock_run.assert_called_once_with(
        ["brightnessctl", "set", "81%"],
        check=True,
        capture_output=True,
        timeout=5.0,
    )
