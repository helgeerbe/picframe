from collections.abc import Callable
from typing import Any, Protocol


class IEventSubscriber(Protocol):
    def subscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        """Subscribe to a specific event type."""
        ...

    def unsubscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        """Unsubscribe from a specific event type."""
        ...


class IEventPublisher(Protocol):
    def publish(self, event: Any) -> None:
        """Publish an event to the bus."""
        ...
