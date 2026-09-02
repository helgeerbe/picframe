"""
Watchdog-backed media filesystem monitoring.

This adapter translates watchdog filesystem events into core FileChangeEvent
DTOs while keeping watchdog dependencies out of the core application layer.
"""

import logging
import os
import threading

from watchdog.events import (
    DirMovedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

from picframe.core.events.dto import FileChangeEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.ports.media_monitor import IMediaMonitor

logger = logging.getLogger(__name__)


class WatchdogMediaMonitorEventHandler(FileSystemEventHandler):
    """
    Translate watchdog filesystem events into FileChangeEvent messages.
    """

    def __init__(self, publisher: IEventPublisher, allowed_extensions: set[str]) -> None:
        self.publisher = publisher
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}

    def is_allowed(self, path: str) -> bool:
        """Return True when the file extension should be monitored."""
        _, ext = os.path.splitext(path)
        return ext.lower() in self.allowed_extensions

    def _publish(self, event_type: str, path: str) -> None:
        if self.is_allowed(path):
            self.publisher.publish(FileChangeEvent(event_type=event_type, path=path))

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        if not event.is_directory and isinstance(event.src_path, str):
            logger.debug(f"File created: {event.src_path}")
            self._publish("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        if not event.is_directory and isinstance(event.src_path, str):
            logger.debug(f"File modified: {event.src_path}")
            self._publish("modified", event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        if not event.is_directory and isinstance(event.src_path, str):
            logger.debug(f"File deleted: {event.src_path}")
            self._publish("deleted", event.src_path)

    def on_moved(self, event: DirMovedEvent | FileMovedEvent) -> None:
        """Handle file move events as deleted + created events."""
        if event.is_directory or not isinstance(event, FileMovedEvent):
            return
        if isinstance(event.src_path, str):
            logger.debug(f"File moved from (deleted): {event.src_path}")
            self._publish("deleted", event.src_path)
        if isinstance(event.dest_path, str):
            logger.debug(f"File moved to (created): {event.dest_path}")
            self._publish("created", event.dest_path)


class WatchdogMediaMonitor(IMediaMonitor):
    """
    Monitor media directories using watchdog observers.

    Standard Observer is used for local directories. PollingObserver is used for
    likely network mounts, which are common for NAS-backed media libraries.
    """

    def __init__(
        self,
        publisher: IEventPublisher,
        directories: list[str],
        allowed_extensions: set[str],
        follow_links: bool = False,
    ) -> None:
        self.publisher = publisher
        self._directories = list(directories)
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self.follow_links = follow_links
        self.observers: list[BaseObserver] = []
        self.handler = WatchdogMediaMonitorEventHandler(
            self.publisher,
            self.allowed_extensions,
        )
        self._lock = threading.Lock()
        self._running = False

    @property
    def directories(self) -> list[str]:
        """Return a copy of the configured directories."""
        return list(self._directories)

    def set_directories(self, directories: list[str]) -> None:
        """Replace monitored directories, restarting observers when needed."""
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self._directories = list(directories)
        if was_running:
            self.start()

    def configure(
        self,
        directories: list[str],
        allowed_extensions: set[str],
        follow_links: bool,
    ) -> None:
        """Replace monitor settings, restarting observers when needed."""
        was_running = self._running
        if was_running:
            self.stop()
        with self._lock:
            self._directories = list(directories)
            self.allowed_extensions = {ext.lower() for ext in allowed_extensions}
            self.follow_links = follow_links
            self.handler.allowed_extensions = set(self.allowed_extensions)
        if was_running:
            self.start()

    def _is_network_mount(self, path: str) -> bool:
        """Return True when a path should use polling-based monitoring."""
        if not os.path.ismount(path):
            return False
        return path != "/"

    def _setup_observers(self) -> None:
        """Create and schedule observers for configured directories."""
        for directory in self._directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist, skipping: {directory}")
                continue

            observer: BaseObserver
            if self._is_network_mount(directory):
                logger.info(f"Using PollingObserver for potential network mount: {directory}")
                observer = PollingObserver()
            else:
                logger.info(f"Using standard Observer for local directory: {directory}")
                observer = Observer()

            observer.schedule(self.handler, directory, recursive=True)
            self.observers.append(observer)

    def start(self) -> None:
        """Start media monitoring."""
        with self._lock:
            if self._running:
                return

            logger.info("Starting WatchdogMediaMonitor...")
            self._setup_observers()
            for observer in self.observers:
                observer.start()

            self._running = True
            logger.info("WatchdogMediaMonitor started.")

    def stop(self) -> None:
        """Stop media monitoring."""
        with self._lock:
            if not self._running:
                return

            logger.info("Stopping WatchdogMediaMonitor...")
            for observer in self.observers:
                observer.stop()
            for observer in self.observers:
                observer.join()

            self.observers.clear()
            self._running = False
            logger.info("WatchdogMediaMonitor stopped.")

    def pause(self) -> None:
        """Pause media monitoring without changing configured directories."""
        self.stop()

    def resume(self) -> None:
        """Resume media monitoring after reconciling missed changes."""
        self.perform_differential_sync()
        self.start()

    def perform_differential_sync(self) -> None:
        """
        Publish created events for all currently available media files.

        The downstream indexer decides whether each file is new, changed,
        restored, or unchanged.
        """
        logger.info(f"Performing differential sync on directories: {self._directories}")

        for directory in self._directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist during sync: {directory}")
                continue

            try:
                for root, _, files in os.walk(directory, followlinks=self.follow_links):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        if self.handler.is_allowed(file_path):
                            logger.debug(f"Sync found file: {file_path}")
                            self.publisher.publish(
                                FileChangeEvent(event_type="created", path=file_path)
                            )
            except Exception as exc:
                logger.error(f"Error during differential sync of {directory}: {exc}")

        logger.info("Differential sync complete.")
