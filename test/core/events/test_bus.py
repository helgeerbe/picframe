import threading
import time
from typing import Any

from picframe.core.events import (
    Command,
    CommandEvent,
    PriorityQueueEventBus,
    State,
    StateEvent,
)


def test_subscribe_and_publish() -> None:
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []

    def callback(event: Any) -> None:
        received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.start()

    event = CommandEvent(Command.NEXT)
    bus.publish(event)

    # Wait a bit for the background thread to process
    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 1
    assert received_events[0] == event


def test_unsubscribe() -> None:
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []

    def callback(event: Any) -> None:
        received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.unsubscribe(CommandEvent, callback)
    bus.start()

    event = CommandEvent(Command.NEXT)
    bus.publish(event)

    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 0


def test_priority_ordering() -> None:
    bus = PriorityQueueEventBus()
    received_events: list[Any] = []
    lock = threading.Lock()

    def callback(event: Any) -> None:
        with lock:
            received_events.append(event)

    bus.subscribe(CommandEvent, callback)
    bus.subscribe(StateEvent, callback)

    # Publish a low priority event first, then a high priority one
    # We don't start the bus yet so they queue up
    low_priority = StateEvent(State.PLAYING)
    high_priority = CommandEvent(Command.NEXT)

    bus.publish(low_priority)
    bus.publish(high_priority)

    bus.start()
    time.sleep(0.1)
    bus.stop()

    assert len(received_events) == 2
    # High priority should be processed first
    assert received_events[0] == high_priority
    assert received_events[1] == low_priority


def test_multiple_subscribers() -> None:
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

    time.sleep(0.1)
    bus.stop()

    assert len(received_1) == 1
    assert len(received_2) == 1
    assert received_1[0] == event
    assert received_2[0] == event


def test_stop_unblocks_queue() -> None:
    bus = PriorityQueueEventBus()
    bus.start()
    # Should not hang indefinitely
    bus.stop()
    assert not bus._running
