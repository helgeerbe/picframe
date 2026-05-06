"""
MediaMonitorService for event-driven file system monitoring.

This module provides the `MediaMonitorService` and its associated event handler
to monitor configured directories for file changes (create, modify, delete, move)
and publish these events to the central Event Bus. It includes support for
detecting network mounts and falling back to polling when necessary.
"""

import logging
import os
import threading

from watchdog.events import DirMovedEvent, FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

from picframe.core.events.dto import FileChangeEvent
from picframe.core.events.interfaces import IEventPublisher

logger = logging.getLogger(__name__)

class MediaMonitorEventHandler(FileSystemEventHandler):
    """
    Event handler for watchdog file system events.
    
    Filters events based on allowed extensions and publishes FileChangeEvent DTOs
    to the Event Bus.
    """
    def __init__(self, publisher: IEventPublisher, allowed_extensions: set[str]) -> None:
        """
        Initialize the event handler.
        
        Args:
            publisher: The Event Bus publisher.
            allowed_extensions: A set of allowed file extensions (e.g., {'.jpg', '.png'}).
        """
        self.publisher = publisher
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}

    def _is_allowed(self, path: str) -> bool:
        """Check if the file extension is allowed."""
        _, ext = os.path.splitext(path)
        return ext.lower() in self.allowed_extensions

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        if (not event.is_directory and isinstance(event.src_path, str) and
                self._is_allowed(event.src_path)):
            logger.debug(f"File created: {event.src_path}")
            self.publisher.publish(FileChangeEvent(event_type="created", path=event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        if (not event.is_directory and isinstance(event.src_path, str) and
                self._is_allowed(event.src_path)):
            logger.debug(f"File modified: {event.src_path}")
            self.publisher.publish(FileChangeEvent(event_type="modified", path=event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        if (not event.is_directory and isinstance(event.src_path, str) and
                self._is_allowed(event.src_path)):
            logger.debug(f"File deleted: {event.src_path}")
            self.publisher.publish(FileChangeEvent(event_type="deleted", path=event.src_path))

    def on_moved(self, event: DirMovedEvent | FileMovedEvent) -> None:
        """Handle file move events, translating them to delete/create events."""
        if not event.is_directory and isinstance(event, FileMovedEvent):
            if isinstance(event.src_path, str) and self._is_allowed(event.src_path):
                logger.debug(f"File moved from (deleted): {event.src_path}")
                self.publisher.publish(FileChangeEvent(event_type="deleted", path=event.src_path))
            if isinstance(event.dest_path, str) and self._is_allowed(event.dest_path):
                logger.debug(f"File moved to (created): {event.dest_path}")
                self.publisher.publish(FileChangeEvent(event_type="created", path=event.dest_path))


class MediaMonitorService:
    """
    Service for monitoring media directories for file changes.
    
    Uses watchdog to detect file system events and publishes them to the Event Bus.
    Supports fallback to PollingObserver for network shares.
    """
    def __init__(
        self, publisher: IEventPublisher, directories: list[str],
        allowed_extensions: set[str], follow_links: bool = False
    ) -> None:
        """
        Initialize the MediaMonitorService.
        
        Args:
            publisher: The Event Bus publisher.
            directories: A list of directory paths to monitor.
            allowed_extensions: A set of allowed file extensions.
            follow_links: Whether to follow symbolic links.
        """
        self.publisher = publisher
        self.directories = directories
        self.allowed_extensions = allowed_extensions
        self.follow_links = follow_links
        self.observers: list[BaseObserver] = []
        self.handler = MediaMonitorEventHandler(self.publisher, self.allowed_extensions)
        self._lock = threading.Lock()
        self._running = False

    def _is_network_mount(self, path: str) -> bool:
        """
        Check if a path is likely a network mount point.
        
        Args:
            path: The directory path to check.
            
        Returns:
            True if the path is considered a network mount, False otherwise.
        """
        # A simple heuristic: if it's a mount point and not the root, it might be a network share.
        # In a real-world scenario, this might need more robust checks
        # (e.g., parsing /proc/mounts on Linux).
        if not os.path.ismount(path):
            return False
        
        # Check if it's a known local filesystem type (Linux specific example)
        try:
            # This is a very basic check and might not be sufficient for all cases.
            # A more robust approach would involve checking the filesystem type.
            # For now, we'll assume any mount point that isn't root could potentially
            # be a network share
            # and might benefit from PollingObserver if standard Observer fails or is unreliable.
            if path == '/':
                return False
            return True
        except Exception as e:
            logger.warning(f"Error checking mount point {path}: {e}")
            return False

    def _setup_observers(self) -> None:
        """Set up watchdog observers for the configured directories."""
        for directory in self.directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist, skipping: {directory}")
                continue

            # Determine if we need a PollingObserver (e.g., for network shares)
            use_polling = self._is_network_mount(directory)
            
            observer: BaseObserver
            if use_polling:
                logger.info(f"Using PollingObserver for potential network mount: {directory}")
                observer = PollingObserver()
            else:
                logger.info(f"Using standard Observer for local directory: {directory}")
                observer = Observer()

            observer.schedule(self.handler, directory, recursive=True)
            self.observers.append(observer)

    def start(self) -> None:
        """Start the media monitor service and its observers."""
        with self._lock:
            if self._running:
                return
            
            logger.info("Starting MediaMonitorService...")
            self._setup_observers()
            
            for observer in self.observers:
                observer.start()
            
            self._running = True
            logger.info("MediaMonitorService started.")

    def stop(self) -> None:
        """Stop the media monitor service and its observers."""
        with self._lock:
            if not self._running:
                return
            
            logger.info("Stopping MediaMonitorService...")
            for observer in self.observers:
                observer.stop()
            
            for observer in self.observers:
                observer.join()
            
            self.observers.clear()
            self._running = False
            logger.info("MediaMonitorService stopped.")

    def perform_differential_sync(self) -> None:
        """
        Performs a fast differential sync on startup using os.walk().
        This should be called before starting the observers to ensure the initial state is correct.
        """
        logger.info(f"Performing differential sync on directories: {self.directories}")
        
        from watchdog.events import FileCreatedEvent
        
        for directory in self.directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist during sync: {directory}")
                continue
            
            try:
                for root, _, files in os.walk(directory, followlinks=self.follow_links):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if self.handler._is_allowed(file_path):
                            logger.debug(f"Sync found file: {file_path}")
                            # Publish synchronously to ensure indexing completes before playlist build
                            self.handler.on_created(FileCreatedEvent(file_path))
            except Exception as e:
                logger.error(f"Error during differential sync of {directory}: {e}")
        
        logger.info("Differential sync complete.")
