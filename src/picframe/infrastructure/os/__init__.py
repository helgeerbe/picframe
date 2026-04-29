"""
OS-specific infrastructure adapters package.
"""

from .hal_factory import HALAdapters, HALFactory
from .mock_adapters import MockDisplayPower, MockHardwareInput, MockSystemManager

__all__ = [
    "HALAdapters",
    "HALFactory",
    "MockDisplayPower",
    "MockHardwareInput",
    "MockSystemManager",
]
