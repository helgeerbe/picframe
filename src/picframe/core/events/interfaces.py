"""
Interfaces for the Event Bus system.

This module defines the core protocols (interfaces) for publishing and
subscribing to events within the application's Event-Driven Architecture.
Using protocols ensures loose coupling between components.
"""

from collections.abc import Callable
from typing import Any, Protocol


class IEventSubscriber(Protocol):
    """
    Protocol defining the contract for subscribing to events.
    """

    def subscribe(self, event_type: type, callback: Callable[[Any], None]) -> None:
        """
        Subscribe a callback function to a specific event type.

        Args:
            event_type: The class of the event to subscribe to.
            callback: A callable that takes the event instance as its argument.
        """
        ...

    def unsubscribe(self, event_type: type, callback: Callable[[Any], None]) -> None:
        """
        Unsubscribe a registered callback from a specific event type.

        Args:
            event_type: The class of the event to unsubscribe from.
            callback: The callable that was previously registered.
        """
        ...


class IEventPublisher(Protocol):
    """
    Protocol defining the contract for publishing events.
    """

    def publish(self, event: Any) -> None:
        """
        Publish an event to the bus, notifying all registered subscribers.

        Args:
            event: The event instance to publish. Must be an instance of
                   a class derived from the base Event class.
        """
        ...
