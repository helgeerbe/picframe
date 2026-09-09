"""
Hardware Abstraction Layer (HAL) Ports package.
"""

from .hal import IDisplayPower, IHardwareInput, ISystemManager, IWakeInputListener
from .overlay import IOverlayController

__all__ = [
    "IDisplayPower",
    "IHardwareInput",
    "ISystemManager",
    "IWakeInputListener",
    "IOverlayController",
]
