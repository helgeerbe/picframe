"""
Tests for the Hardware Abstraction Layer (HAL) Factory.
"""

import sys
from typing import Any
from unittest.mock import patch

from picframe.infrastructure.os.hal_factory import HALFactory
from picframe.infrastructure.os.mock_adapters import (
    MockDisplayPower,
    MockHardwareInput,
    MockSystemManager,
)


def test_hal_factory_darwin() -> None:
    """Test that the HAL factory injects mock adapters on macOS."""
    with patch.object(sys, "platform", "darwin"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, MockDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, MockSystemManager)


def test_hal_factory_win32() -> None:
    """Test that the HAL factory injects mock adapters on Windows."""
    with patch.object(sys, "platform", "win32"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, MockDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, MockSystemManager)


@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_raspberry_pi", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_wayland", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_x11", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._has_wlr_randr", return_value=True)
def test_hal_factory_rpi_wayland_with_config(
    mock_wlr: Any, mock_x11: Any, mock_wayland: Any, mock_rpi: Any
) -> None:
    """Test the HAL factory injects correct adapters for RPi on Wayland with config."""
    from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager
    from picframe.infrastructure.os.rpi_gpio_adapter import RPiGPIOAdapter
    from picframe.infrastructure.os.wayland_power import WaylandDisplayPower

    with patch.object(sys, "platform", "linux"):
        config = {"btn1": {"type": "button", "pin": 17}}
        adapters = HALFactory.create_adapters(hardware_input_config=config)

        assert isinstance(adapters.display_power, WaylandDisplayPower)
        assert isinstance(adapters.hardware_input, RPiGPIOAdapter)
        assert isinstance(adapters.system_manager, LinuxSystemManager)


@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_raspberry_pi", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_wayland", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_x11", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._has_wlr_randr", return_value=True)
def test_hal_factory_rpi_wayland_no_config(
    mock_wlr: Any, mock_x11: Any, mock_wayland: Any, mock_rpi: Any
) -> None:
    """Test that the HAL factory falls back to MockHardwareInput if config is missing on RPi."""
    from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager
    from picframe.infrastructure.os.wayland_power import WaylandDisplayPower

    with patch.object(sys, "platform", "linux"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, WaylandDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, LinuxSystemManager)


@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_raspberry_pi", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_wayland", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_x11", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._has_wlr_randr", return_value=False)
def test_hal_factory_generic_linux_wayland_no_wlr(
    mock_wlr: Any, mock_x11: Any, mock_wayland: Any, mock_rpi: Any
) -> None:
    """Test that the HAL factory falls back to MockDisplayPower if wlr-randr is missing."""
    from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager

    with patch.object(sys, "platform", "linux"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, MockDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, LinuxSystemManager)


@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_raspberry_pi", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_wayland", return_value=False)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._is_x11", return_value=True)
@patch("picframe.infrastructure.os.hal_factory.HALFactory._has_wlr_randr", return_value=False)
def test_hal_factory_x11_fallback(
    mock_wlr: Any, mock_x11: Any, mock_wayland: Any, mock_rpi: Any
) -> None:
    """Test that the HAL factory falls back to Mock adapters on X11."""
    from picframe.infrastructure.os.linux_system_manager import LinuxSystemManager

    with patch.object(sys, "platform", "linux"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, MockDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, LinuxSystemManager)


def test_is_raspberry_pi_detection() -> None:
    """Test the Raspberry Pi hardware detection logic."""
    from unittest.mock import mock_open

    # Test positive case
    with patch("builtins.open", mock_open(read_data="Raspberry Pi 4 Model B Rev 1.2")):
        assert HALFactory._is_raspberry_pi() is True

    # Test negative case
    with patch("builtins.open", mock_open(read_data="Generic x86 PC")):
        assert HALFactory._is_raspberry_pi() is False

    # Test file not found (e.g., standard Ubuntu VM)
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert HALFactory._is_raspberry_pi() is False
