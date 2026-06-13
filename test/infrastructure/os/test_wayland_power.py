"""
Tests for the WaylandDisplayPower adapter.
"""

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

from picframe.core.events.dto import SystemErrorEvent
from picframe.infrastructure.os.wayland_power import WaylandDisplayPower


def test_wayland_power_initialization() -> None:
    """Test that the adapter initializes with the correct default output."""
    adapter = WaylandDisplayPower()
    assert adapter._display_output == "HDMI-A-1"
    assert adapter.is_on() is True

    adapter_custom = WaylandDisplayPower(display_output="DSI-1")
    assert adapter_custom._display_output == "DSI-1"


def test_wayland_power_can_retarget_display_output() -> None:
    adapter = WaylandDisplayPower(display_output="HDMI-A-1")

    adapter.set_display_output("HDMI-A-2")

    assert adapter._display_output == "HDMI-A-2"


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
    """Test that the adapter handles wlr-randr execution errors gracefully and publishes an event."""
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
