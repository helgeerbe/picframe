"""
Thread-safe Event Bus implementation using a PriorityQueue.

This module provides the central communication hub for the application.
It allows asynchronous background threads (like MQTT or FastAPI) to safely
publish events to the synchronous main render loop, ensuring that critical
commands preempt standard state updates.
"""
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from .dto import Event, SystemErrorEvent
from .interfaces import IEventPublisher, IEventSubscriber

logger = logging.getLogger(__name__)


class PriorityQueueEventBus(IEventPublisher, IEventSubscriber):
    """
    A thread-safe event bus that processes events based on their priority.

    Implements both IEventPublisher and IEventSubscriber protocols.
    Uses a background worker thread to dispatch events to subscribers.
    """

    def __init__(self) -> None:
        """Initialize the event bus with an empty queue and subscriber dict."""
        self._subscribers: dict[type, list[Callable[[Any], None]]] = {}
        self._queue: queue.PriorityQueue[tuple[int, int, Any]] = (
            queue.PriorityQueue()
        )
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._counter = 0

    def subscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        """Register a callback for a specific event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(
        self, event_type: type, callback: Callable[[Any], None]
    ) -> None:
        """Remove a registered callback for a specific event type."""
        with self._lock:
            if event_type in self._subscribers:
                if callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)

    def publish(self, event: Event) -> None:
        """
        Publish an event to the bus.

        The event is placed in a PriorityQueue, sorted by its priority.
        """
        with self._lock:
            self._counter += 1
            self._queue.put((event.priority, self._counter, event))

    def start(self) -> None:
        """Start the background worker thread to process events."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._process_events, daemon=True
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop the background worker thread and unblock the queue."""
        worker_thread: threading.Thread | None = None
        with self._lock:
            self._running = False
            # Put a dummy event to unblock the queue if it's waiting
            self._counter += 1
            self._queue.put((0, self._counter, None))
            worker_thread = self._worker_thread
        if worker_thread and worker_thread is not threading.current_thread():
            worker_thread.join()

    def _process_events(self) -> None:
        """
        Main loop for the background worker thread.

        Continuously pulls events from the PriorityQueue and dispatches
        them to all registered subscribers.
        """
        while self._running:
            try:
                # Block until an item is available
                _, _, event = self._queue.get(timeout=1.0)
                if event is None:
                    self._queue.task_done()
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
                        self._handle_callback_error(event, callback, e)

                self._queue.task_done()
            except queue.Empty:
                continue

    def _handle_callback_error(
        self,
        event: Any,
        callback: Callable[[Any], None],
        error: Exception,
    ) -> None:
        """Log subscriber failures and emit one poison-pill event when safe."""
        callback_name = getattr(callback, "__qualname__", repr(callback))
        event_name = type(event).__name__
        logger.error(
            "Error in event callback %s while handling %s: %s",
            callback_name,
            event_name,
            error,
            exc_info=True,
        )
        if isinstance(event, SystemErrorEvent):
            return

        try:
            self.publish(
                SystemErrorEvent(
                    message=f"{event_name} subscriber {callback_name} failed: {error}",
                    component="PriorityQueueEventBus",
                )
            )
        except Exception:
            logger.exception("Failed to publish SystemErrorEvent for subscriber failure.")
