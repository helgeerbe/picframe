"""
Unit tests for the PriorityQueueEventBus.

This module tests the core functionality of the event bus, including
subscribing, unsubscribing, publishing events, priority-based ordering,
and thread-safe execution of callbacks.
"""
import threading
import time
from typing import Any

from picframe.core.events import (
    Command,
    CommandEvent,
    PriorityQueueEventBus,
    State,
    StateEvent,
    SystemErrorEvent,
)


def test_subscribe_and_publish() -> None:
    """
    Test that a subscribed callback receives published events.

    Expected behavior:
        The callback should be invoked with the exact event that was published.
    """
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []

    def callback(event: Any) -> None:
        received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.start()

    event = CommandEvent(Command.NEXT)
    bus.publish(event)

    # Wait briefly to allow the background worker thread to process the queue
    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 1
    assert received_events[0] == event


def test_unsubscribe() -> None:
    """
    Test that unsubscribing removes the callback from the event bus.

    Expected behavior:
        After unsubscribing, the callback should no longer receive events
        of that type.
    """
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []

    def callback(event: Any) -> None:
        received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.unsubscribe(CommandEvent, callback)
    bus.start()

    event = CommandEvent(Command.NEXT)
    bus.publish(event)

    # Wait briefly to ensure no events are processed by the removed callback
    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 0


def test_priority_ordering() -> None:
    """
    Test that events are processed in order of their priority.

    Expected behavior:
        High-priority events (lower integer value) should be processed
        before low-priority events, regardless of publish order.
    """
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []
    # Lock required because the callback is executed in the bus's worker thread
    lock = threading.Lock()

    def callback(event: Any) -> None:
        with lock:
            received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.subscribe(StateEvent, callback)

    # Publish a low priority event first, then a high priority one.
    # The bus is not started yet, so they will queue up and be sorted.
    low_priority = StateEvent(State.PLAYING)
    high_priority = CommandEvent(Command.NEXT)

    bus.publish(low_priority)
    bus.publish(high_priority)

    bus.start()
    # Wait briefly to allow the background worker thread to process the queue
    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 2
    # High priority should be processed first due to PriorityQueue sorting
    assert received_events[0] == high_priority
    assert received_events[1] == low_priority


def test_multiple_subscribers() -> None:
    """
    Test that multiple subscribers to the same event type receive the event.

    Expected behavior:
        Every registered callback for a given event type should be invoked.
    """
    bus = PriorityQueueEventBus()
    received_1: list[Any] = []
    received_2: list[Any] = []

    def callback1(event: Any) -> None:
        received_1.append(event)

    def callback2(event: Any) -> None:
        received_2.append(event)

    bus.subscribe(CommandEvent, callback1)
    bus.subscribe(CommandEvent, callback2)
    bus.start()

    event = CommandEvent(Command.NEXT)
    bus.publish(event)

    # Wait briefly to allow the background worker thread to process the queue
    time.sleep(0.1)
    bus.stop()

    assert len(received_1) == 1
    assert len(received_2) == 1
    assert received_1[0] == event
    assert received_2[0] == event


def test_stop_unblocks_queue() -> None:
    """
    Test that stopping the event bus unblocks the internal queue.

    Expected behavior:
        Calling stop() should inject a sentinel value to unblock queue.get()
        call, allowing the worker thread to terminate cleanly without hanging.
    """
    bus = PriorityQueueEventBus()
    bus.start()
    # Should not hang indefinitely waiting for an event
    bus.stop()
    assert not bus._running


def test_callback_failure_publishes_system_error_event() -> None:
    """Subscriber failures should become one poison-pill event."""
    bus = PriorityQueueEventBus()
    received_errors: list[SystemErrorEvent] = []

    def failing_callback(event: Any) -> None:
        raise RuntimeError("boom")

    def error_callback(event: SystemErrorEvent) -> None:
        received_errors.append(event)

    bus.subscribe(CommandEvent, failing_callback)
    bus.subscribe(SystemErrorEvent, error_callback)
    bus.start()

    bus.publish(CommandEvent(Command.NEXT))

    time.sleep(0.1)
    bus.stop()

    assert len(received_errors) == 1
    assert received_errors[0].component == "PriorityQueueEventBus"
    assert "CommandEvent subscriber" in received_errors[0].message
    assert "boom" in received_errors[0].message


def test_system_error_callback_failure_does_not_recurse() -> None:
    """Failed poison-pill handlers are logged but do not create error loops."""
    bus = PriorityQueueEventBus()
    observed_errors: list[SystemErrorEvent] = []

    def failing_error_callback(event: SystemErrorEvent) -> None:
        observed_errors.append(event)
        raise RuntimeError("error handler failed")

    bus.subscribe(SystemErrorEvent, failing_error_callback)
    bus.start()

    original = SystemErrorEvent(message="original", component="test")
    bus.publish(original)

    time.sleep(0.1)
    bus.stop()

    assert observed_errors == [original]
