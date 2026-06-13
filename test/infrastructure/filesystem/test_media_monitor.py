from unittest.mock import MagicMock, Mock, patch

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from picframe.core.events.dto import FileChangeEvent
from picframe.infrastructure.filesystem.media_monitor import (
    WatchdogMediaMonitor,
    WatchdogMediaMonitorEventHandler,
)


class FakeObserver:
    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.start_count = 0
        self.stop_count = 0
        self.join_count = 0

    def schedule(self, handler: object, directory: str, recursive: bool) -> None:
        self.scheduled.append((handler, directory, recursive))

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1

    def join(self) -> None:
        self.join_count += 1


def test_event_handler_allows_configured_extensions() -> None:
    handler = WatchdogMediaMonitorEventHandler(Mock(), {".jpg", ".png"})

    assert handler.is_allowed("test.jpg") is True
    assert handler.is_allowed("test.PNG") is True
    assert handler.is_allowed("test.txt") is False


def test_event_handler_publishes_created_event() -> None:
    publisher = Mock()
    handler = WatchdogMediaMonitorEventHandler(publisher, {".jpg"})

    handler.on_created(FileCreatedEvent("/path/to/image.jpg"))

    publisher.publish.assert_called_once_with(
        FileChangeEvent(event_type="created", path="/path/to/image.jpg")
    )


def test_event_handler_ignores_unconfigured_extension() -> None:
    publisher = Mock()
    handler = WatchdogMediaMonitorEventHandler(publisher, {".jpg"})

    handler.on_created(FileCreatedEvent("/path/to/text.txt"))

    publisher.publish.assert_not_called()


def test_event_handler_publishes_modified_event() -> None:
    publisher = Mock()
    handler = WatchdogMediaMonitorEventHandler(publisher, {".jpg"})

    handler.on_modified(FileModifiedEvent("/path/to/image.jpg"))

    publisher.publish.assert_called_once_with(
        FileChangeEvent(event_type="modified", path="/path/to/image.jpg")
    )


def test_event_handler_publishes_deleted_event() -> None:
    publisher = Mock()
    handler = WatchdogMediaMonitorEventHandler(publisher, {".jpg"})

    handler.on_deleted(FileDeletedEvent("/path/to/image.jpg"))

    publisher.publish.assert_called_once_with(
        FileChangeEvent(event_type="deleted", path="/path/to/image.jpg")
    )


def test_event_handler_publishes_move_as_delete_and_create() -> None:
    publisher = Mock()
    handler = WatchdogMediaMonitorEventHandler(publisher, {".jpg"})

    handler.on_moved(FileMovedEvent("/path/to/old.jpg", "/path/to/new.jpg"))

    assert publisher.publish.call_count == 2
    publisher.publish.assert_any_call(
        FileChangeEvent(event_type="deleted", path="/path/to/old.jpg")
    )
    publisher.publish.assert_any_call(
        FileChangeEvent(event_type="created", path="/path/to/new.jpg")
    )


@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.ismount")
def test_setup_observers_local(
    mock_ismount: MagicMock,
    mock_exists: MagicMock,
) -> None:
    mock_exists.return_value = True
    mock_ismount.return_value = False

    service = WatchdogMediaMonitor(Mock(), ["/local/dir"], {".jpg"})
    service._setup_observers()

    assert len(service.observers) == 1
    from watchdog.observers import Observer

    assert isinstance(service.observers[0], Observer)


@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.ismount")
def test_setup_observers_network(
    mock_ismount: MagicMock,
    mock_exists: MagicMock,
) -> None:
    mock_exists.return_value = True
    mock_ismount.return_value = True

    service = WatchdogMediaMonitor(Mock(), ["/mnt/network"], {".jpg"})
    service._setup_observers()

    assert len(service.observers) == 1
    from watchdog.observers.polling import PollingObserver

    assert isinstance(service.observers[0], PollingObserver)


@patch("picframe.infrastructure.filesystem.media_monitor.os.walk")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
def test_perform_differential_sync_publishes_allowed_files(
    mock_exists: MagicMock,
    mock_walk: MagicMock,
) -> None:
    publisher = Mock()
    mock_exists.return_value = True
    mock_walk.return_value = [
        ("/dir", [], ["image1.jpg", "text.txt"]),
        ("/dir/sub", [], ["image2.PNG"]),
    ]
    service = WatchdogMediaMonitor(publisher, ["/dir"], {".jpg", ".png"})

    service.perform_differential_sync()

    mock_walk.assert_called_once_with("/dir", followlinks=False)
    assert publisher.publish.call_args_list == [
        ((FileChangeEvent(event_type="created", path="/dir/image1.jpg"),),),
        ((FileChangeEvent(event_type="created", path="/dir/sub/image2.PNG"),),),
    ]


@patch("picframe.infrastructure.filesystem.media_monitor.os.walk")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
def test_perform_differential_sync_honors_follow_links(
    mock_exists: MagicMock,
    mock_walk: MagicMock,
) -> None:
    mock_exists.return_value = True
    mock_walk.return_value = []
    service = WatchdogMediaMonitor(Mock(), ["/dir"], {".jpg"}, follow_links=True)

    service.perform_differential_sync()

    mock_walk.assert_called_once_with("/dir", followlinks=True)


@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
def test_perform_differential_sync_skips_missing_directory(
    mock_exists: MagicMock,
) -> None:
    publisher = Mock()
    mock_exists.return_value = False
    service = WatchdogMediaMonitor(publisher, ["/missing"], {".jpg"})

    service.perform_differential_sync()

    publisher.publish.assert_not_called()


@patch("picframe.infrastructure.filesystem.media_monitor.Observer")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.ismount")
def test_start_stop_are_idempotent(
    mock_ismount: MagicMock,
    mock_exists: MagicMock,
    mock_observer_class: MagicMock,
) -> None:
    fake_observer = FakeObserver()
    mock_exists.return_value = True
    mock_ismount.return_value = False
    mock_observer_class.return_value = fake_observer
    service = WatchdogMediaMonitor(Mock(), ["/dir"], {".jpg"})

    service.start()
    service.start()

    assert fake_observer.scheduled[0][1:] == ("/dir", True)
    assert fake_observer.start_count == 1
    assert mock_observer_class.call_count == 1

    service.stop()
    service.stop()

    assert fake_observer.stop_count == 1
    assert fake_observer.join_count == 1
    assert service.observers == []


@patch("picframe.infrastructure.filesystem.media_monitor.Observer")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.ismount")
def test_set_directories_restarts_running_monitor(
    mock_ismount: MagicMock,
    mock_exists: MagicMock,
    mock_observer_class: MagicMock,
) -> None:
    first_observer = FakeObserver()
    second_observer = FakeObserver()
    mock_exists.return_value = True
    mock_ismount.return_value = False
    mock_observer_class.side_effect = [first_observer, second_observer]
    service = WatchdogMediaMonitor(Mock(), ["/first"], {".jpg"})

    service.start()
    service.set_directories(["/second"])

    assert first_observer.stop_count == 1
    assert first_observer.join_count == 1
    assert second_observer.scheduled[0][1:] == ("/second", True)
    assert second_observer.start_count == 1
    assert service.directories == ["/second"]


@patch("picframe.infrastructure.filesystem.media_monitor.Observer")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.exists")
@patch("picframe.infrastructure.filesystem.media_monitor.os.path.ismount")
def test_configure_restarts_running_monitor_and_updates_settings(
    mock_ismount: MagicMock,
    mock_exists: MagicMock,
    mock_observer_class: MagicMock,
) -> None:
    first_observer = FakeObserver()
    second_observer = FakeObserver()
    mock_exists.return_value = True
    mock_ismount.return_value = False
    mock_observer_class.side_effect = [first_observer, second_observer]
    service = WatchdogMediaMonitor(Mock(), ["/first"], {".jpg"})

    service.start()
    service.configure(["/second"], {".PNG", ".MP4"}, follow_links=True)

    assert first_observer.stop_count == 1
    assert first_observer.join_count == 1
    assert second_observer.scheduled[0][1:] == ("/second", True)
    assert second_observer.start_count == 1
    assert service.directories == ["/second"]
    assert service.allowed_extensions == {".png", ".mp4"}
    assert service.handler.allowed_extensions == {".png", ".mp4"}
    assert service.follow_links is True
