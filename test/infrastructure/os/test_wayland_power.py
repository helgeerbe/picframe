"""
Tests for the WaylandDisplayPower adapter.
"""

import subprocess
from typing import Any
from unittest.mock import patch

from picframe.infrastructure.os.wayland_power import WaylandDisplayPower


def test_wayland_power_initialization() -> None:
    """Test that the adapter initializes with the correct default output."""
    adapter = WaylandDisplayPower()
    assert adapter._display_output == "HDMI-A-1"
    assert adapter.is_on() is True

    adapter_custom = WaylandDisplayPower(display_output="DSI-1")
    assert adapter_custom._display_output == "DSI-1"


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
    """Test that the adapter handles wlr-randr execution errors gracefully."""
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd="wlr-randr", stderr=b"Error"
    )
    adapter = WaylandDisplayPower()

    # Should not raise an exception
    adapter.turn_off()
    # State should remain unchanged if the command failed
    assert adapter.is_on() is True


@patch("subprocess.run")
def test_wayland_power_handles_file_not_found(mock_run: Any) -> None:
    """Test that the adapter handles missing wlr-randr gracefully."""
    mock_run.side_effect = FileNotFoundError()
    adapter = WaylandDisplayPower()

    # Should not raise an exception
    adapter.turn_off()
    # State should remain unchanged if the command failed
    assert adapter.is_on() is True
