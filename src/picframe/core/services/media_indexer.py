"""
Media Indexer Service.

This module provides the `MediaIndexerService` which listens to file system
events and updates the media repository with extracted metadata.
"""

import logging
import os

from picframe.core.events.dto import Command, CommandEvent, FileChangeEvent
from picframe.core.events.interfaces import IEventSubscriber
from picframe.core.metadata.interfaces import IMetadataStrategy
from picframe.core.ports.media_monitor import IMediaMonitor
from picframe.core.repositories.interfaces import IConfigRepository, IMediaRepository
from picframe.core.services.image_processing import ImageProcessingService
from picframe.core.services.geocoding_worker import GeocodingWorker

logger = logging.getLogger(__name__)


class MediaIndexerService:
    """
    Listens to FileChangeEvents and updates the MediaRepository.
    
    This service acts as the bridge between the file system monitor and the
    database, ensuring that the media cache is kept up-to-date with the
    actual files on disk.
    """
    def __init__(
        self,
        event_subscriber: IEventSubscriber,
        media_repository: IMediaRepository,
        config_repository: IConfigRepository,
        image_processing_service: ImageProcessingService,
        media_monitor_service: IMediaMonitor,
        image_strategy: IMetadataStrategy,
        video_strategy: IMetadataStrategy
    ) -> None:
        self.media_repository = media_repository
        self.config_repository = config_repository
        self.image_processing_service = image_processing_service
        self.media_monitor_service = media_monitor_service
        self.image_strategy = image_strategy
        self.video_strategy = video_strategy
        self._paused = False
        self._stopped = False
        
        # Initialize and start the geocoding worker
        self.geocoding_worker = GeocodingWorker(media_repository, config_repository, event_subscriber)
        self.geocoding_worker.start()
        
        event_subscriber.subscribe(FileChangeEvent, self._handle_file_change)
        event_subscriber.subscribe(CommandEvent, self._handle_command)

    def _get_or_create_directory_id(self, filepath: str) -> int:
        """
        Resolve the directory ID for a given filepath, creating it if necessary.
        """
        dir_path = os.path.dirname(filepath)
        directories = self.config_repository.get_all_directories()
        
        for d in directories:
            if d["path"] == dir_path:
                return int(d["id"])
                
        # If not found, add it
        return self.config_repository.add_directory(dir_path)

    def _handle_file_change(self, event: FileChangeEvent) -> None:
        if self._paused or self._stopped:
            logger.debug(f"Ignoring file change while indexer is paused/stopped: {event.path}")
            return

        try:
            if event.event_type in ("created", "modified"):
                ext = os.path.splitext(event.path)[1].lower()
                
                # Get extensions from config
                image_exts = self.config_repository.get_app_config("model.image_extensions", [
                    ".jpg", ".jpeg", ".png", ".heic", ".heif"
                ])
                video_exts = self.config_repository.get_app_config("model.video_extensions", [
                    ".mp4", ".mkv", ".flv", ".mov", ".avi", ".webm", ".hevc"
                ])
                
                # Ensure extensions are lowercase for comparison
                image_exts = [e.lower() for e in image_exts]
                video_exts = [e.lower() for e in video_exts]
                
                strategy = None
                if ext in image_exts:
                    strategy = self.image_strategy
                elif ext in video_exts:
                    strategy = self.video_strategy
                    
                if not strategy:
                    logger.debug(f"Skipping file with unsupported extension: {event.path}")
                    return

                file_stat = self._get_file_stat(event.path)
                if file_stat is None:
                    logger.warning(f"File not found during indexing, marking inactive: {event.path}")
                    self.media_repository.delete_media_by_path(event.path)
                    return

                if not self._should_index_file(event.path, file_stat):
                    logger.debug(f"Skipping unchanged media file: {event.path}")
                    return

                logger.debug(f"Indexing file: {event.path}")
                # Extract metadata
                directory_id = self._get_or_create_directory_id(event.path)
                
                # For initial sync, we need this to be synchronous so the DB is populated
                # before the playlist is built.
                media_item = strategy.extract(event.path, directory_id)
                if media_item:
                    self.media_repository.add_media_item(media_item.to_dict())
                    
                    # Queue coordinates for reverse geocoding if present
                    if media_item.latitude is not None and media_item.longitude is not None:
                        self.geocoding_worker.queue_lookup(media_item.latitude, media_item.longitude)
                else:
                    logger.warning(f"Failed to extract metadata for {event.path}")
            elif event.event_type == "deleted":
                logger.info(f"Removing file from index: {event.path}")
                self.media_repository.delete_media_by_path(event.path)
        except Exception as e:
            logger.error(f"Error indexing file {event.path}: {e}")

    @staticmethod
    def _get_file_stat(filepath: str) -> os.stat_result | None:
        if not os.path.isfile(filepath):
            return None
        try:
            return os.stat(filepath)
        except OSError:
            return None

    def _should_index_file(self, filepath: str, file_stat: os.stat_result) -> bool:
        existing = self.media_repository.get_media_by_path(filepath)
        if not existing:
            return True
        if bool(existing.get("is_deleted")):
            return True

        try:
            stored_size = int(existing.get("file_size", -1))
            stored_mtime = float(existing.get("last_modified", -1.0))
        except (TypeError, ValueError):
            return True

        return (
            stored_size != int(file_stat.st_size)
            or abs(stored_mtime - float(file_stat.st_mtime)) > 1e-6
        )

    def _handle_command(self, event: CommandEvent) -> None:
        if self._stopped:
            return

        if event.command == Command.SET_CONFIG:
            payload = event.payload or {}
            if "model" in payload and "pic_dir" in payload["model"]:
                new_pic_dir = payload["model"]["pic_dir"]
                logger.info(f"Configuration changed: pic_dir updated to {new_pic_dir}")
                
                # 1. Update media monitor directories
                # We need to stop it, update directories, and restart it
                self.media_monitor_service.stop()
                
                # Expand user path if necessary
                expanded_dir = os.path.expanduser(new_pic_dir)
                self.media_monitor_service.set_directories([expanded_dir])
                
                # 2. Trigger a differential sync to index new files
                self.media_monitor_service.perform_differential_sync()
                
                # 3. Restart the monitor
                self.media_monitor_service.start()
                
                logger.info("Media directory sync complete; purge remains an explicit maintenance action.")

    def pause(self) -> None:
        """Pause indexing and file monitoring."""
        if self._paused or self._stopped:
            return
        logger.info("Pausing MediaIndexerService.")
        self._paused = True
        self.media_monitor_service.pause()
        self.image_processing_service.pause()

    def resume(self) -> None:
        """Resume indexing after reconciling missed filesystem changes."""
        if self._stopped or not self._paused:
            return
        logger.info("Resuming MediaIndexerService.")
        self._paused = False
        self.image_processing_service.resume()
        self.media_monitor_service.resume()

    def stop(self) -> None:
        """Stop indexing, monitoring, and background geocoding."""
        if self._stopped:
            return
        logger.info("Stopping MediaIndexerService.")
        self._stopped = True
        self._paused = False
        self.media_monitor_service.stop()
        self.geocoding_worker.stop()
