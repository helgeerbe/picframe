import queue
import threading
from collections.abc import Callable
from typing import Any

from .dto import Event
from .interfaces import IEventPublisher, IEventSubscriber


class PriorityQueueEventBus(IEventPublisher, IEventSubscriber):
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable[[Any], None]]] = {}
        self._queue: queue.PriorityQueue[tuple[int, Any]] = (
            queue.PriorityQueue()
        )
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: threading.Thread | None = None

    def subscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        with self._lock:
            if event_type in self._subscribers:
                if callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)

    def publish(self, event: Event) -> None:
        # PriorityQueue sorts by the first element of the tuple.
        # We use the event's priority property.
        self._queue.put((event.priority, event))

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._process_events, daemon=True
            )
            self._worker_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            # Put a dummy event to unblock the queue if it's waiting
            self._queue.put((0, None))
            if self._worker_thread:
                self._worker_thread.join()

    def _process_events(self) -> None:
        while self._running:
            try:
                # Block until an item is available
                _, event = self._queue.get(timeout=1.0)
                if event is None:
                    continue  # Stop signal

                event_type = type(event)
                callbacks = []
                with self._lock:
                    if event_type in self._subscribers:
                        callbacks = list(self._subscribers[event_type])

                for callback in callbacks:
                    try:
                        callback(event)
                    except Exception as e:
                        # In a real system, we'd log this error
                        print(f"Error in event callback: {e}")

                self._queue.task_done()
            except queue.Empty:
                continue
