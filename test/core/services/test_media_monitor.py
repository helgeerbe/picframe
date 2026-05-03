import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent

from picframe.core.services.media_monitor import MediaMonitorEventHandler, MediaMonitorService
from picframe.core.events.dto import FileChangeEvent

@pytest.fixture
def mock_publisher():
    return Mock()

class TestMediaMonitorEventHandler:
    def test_is_allowed(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg", ".png"})
        assert handler._is_allowed("test.jpg") is True
        assert handler._is_allowed("test.PNG") is True
        assert handler._is_allowed("test.txt") is False

    def test_on_created(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg"})
        event = FileCreatedEvent("/path/to/image.jpg")
        handler.on_created(event)
        mock_publisher.publish.assert_called_once_with(FileChangeEvent(event_type="created", path="/path/to/image.jpg"))

    def test_on_created_ignored_extension(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg"})
        event = FileCreatedEvent("/path/to/text.txt")
        handler.on_created(event)
        mock_publisher.publish.assert_not_called()

    def test_on_modified(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg"})
        event = FileModifiedEvent("/path/to/image.jpg")
        handler.on_modified(event)
        mock_publisher.publish.assert_called_once_with(FileChangeEvent(event_type="modified", path="/path/to/image.jpg"))

    def test_on_deleted(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg"})
        event = FileDeletedEvent("/path/to/image.jpg")
        handler.on_deleted(event)
        mock_publisher.publish.assert_called_once_with(FileChangeEvent(event_type="deleted", path="/path/to/image.jpg"))

    def test_on_moved(self, mock_publisher):
        handler = MediaMonitorEventHandler(mock_publisher, {".jpg"})
        event = FileMovedEvent("/path/to/old.jpg", "/path/to/new.jpg")
        handler.on_moved(event)
        assert mock_publisher.publish.call_count == 2
        mock_publisher.publish.assert_any_call(FileChangeEvent(event_type="deleted", path="/path/to/old.jpg"))
        mock_publisher.publish.assert_any_call(FileChangeEvent(event_type="created", path="/path/to/new.jpg"))

class TestMediaMonitorService:
    @patch("picframe.core.services.media_monitor.os.path.exists")
    @patch("picframe.core.services.media_monitor.os.path.ismount")
    def test_setup_observers_local(self, mock_ismount, mock_exists, mock_publisher):
        mock_exists.return_value = True
        mock_ismount.return_value = False
        
        service = MediaMonitorService(mock_publisher, ["/local/dir"], {".jpg"})
        service._setup_observers()
        
        assert len(service.observers) == 1
        from watchdog.observers import Observer
        assert isinstance(service.observers[0], Observer)

    @patch("picframe.core.services.media_monitor.os.path.exists")
    @patch("picframe.core.services.media_monitor.os.path.ismount")
    def test_setup_observers_network(self, mock_ismount, mock_exists, mock_publisher):
        mock_exists.return_value = True
        mock_ismount.return_value = True
        
        service = MediaMonitorService(mock_publisher, ["/mnt/network"], {".jpg"})
        service._setup_observers()
        
        assert len(service.observers) == 1
        from watchdog.observers.polling import PollingObserver
        assert isinstance(service.observers[0], PollingObserver)

    @patch("picframe.core.services.media_monitor.os.scandir")
    @patch("picframe.core.services.media_monitor.os.path.exists")
    def test_perform_differential_sync(self, mock_exists, mock_scandir, mock_publisher):
        mock_exists.return_value = True
        
        mock_entry1 = MagicMock()
        mock_entry1.is_file.return_value = True
        mock_entry1.path = "/dir/image1.jpg"
        
        mock_entry2 = MagicMock()
        mock_entry2.is_file.return_value = True
        mock_entry2.path = "/dir/text.txt"
        
        mock_scandir.return_value = [mock_entry1, mock_entry2]
        
        service = MediaMonitorService(mock_publisher, ["/dir"], {".jpg"})
        service.perform_differential_sync()
        
        # Currently perform_differential_sync just logs, so we just ensure it runs without error
        # and calls scandir correctly.
        mock_scandir.assert_called_once_with("/dir")
