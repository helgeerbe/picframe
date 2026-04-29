"""
Tests for the Hardware Abstraction Layer (HAL) Factory.
"""

import sys
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


def test_hal_factory_linux_default() -> None:
    """Test that the HAL factory injects WaylandDisplayPower on Linux."""
    from picframe.infrastructure.os.wayland_power import WaylandDisplayPower
    with patch.object(sys, "platform", "linux"):
        adapters = HALFactory.create_adapters()

        assert isinstance(adapters.display_power, WaylandDisplayPower)
        assert isinstance(adapters.hardware_input, MockHardwareInput)
        assert isinstance(adapters.system_manager, MockSystemManager)
