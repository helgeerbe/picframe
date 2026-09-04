"""
Core Event Bus module for Picframe.

This package provides the central Event-Driven Architecture (EDA) components,
including the thread-safe PriorityQueueEventBus, immutable Event DTOs, and
the publisher/subscriber interfaces. It facilitates decoupled communication
between the asynchronous control plane and the synchronous render loop.
"""

from .bus import PriorityQueueEventBus
from .dto import (
    Command,
    CommandEvent,
    Event,
    FileChangeEvent,
    RenderCommand,
    State,
    StateEvent,
    SystemErrorEvent,
    VideoPlaybackDiagnosticsEvent,
    VideoPlaybackWarningEvent,
)
from .interfaces import IEventPublisher, IEventSubscriber

__all__ = [
    "PriorityQueueEventBus",
    "IEventPublisher",
    "IEventSubscriber",
    "Event",
    "CommandEvent",
    "StateEvent",
    "RenderCommand",
    "FileChangeEvent",
    "SystemErrorEvent",
    "VideoPlaybackDiagnosticsEvent",
    "VideoPlaybackWarningEvent",
    "Command",
    "State",
]
