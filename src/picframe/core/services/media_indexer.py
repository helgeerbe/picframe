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
from picframe.core.repositories.interfaces import IConfigRepository, IMediaRepository
from picframe.core.services.image_processing import ImageProcessingService
from picframe.core.services.media_monitor import MediaMonitorService  # type: ignore
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
        media_monitor_service: MediaMonitorService,
        image_strategy: IMetadataStrategy,
        video_strategy: IMetadataStrategy
    ) -> None:
        self.media_repository = media_repository
        self.config_repository = config_repository
        self.image_processing_service = image_processing_service
        self.media_monitor_service = media_monitor_service
        self.image_strategy = image_strategy
        self.video_strategy = video_strategy
        
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
        try:
            if event.event_type in ("created", "modified"):
                logger.debug(f"Indexing file: {event.path}")
                # Extract metadata
                directory_id = self._get_or_create_directory_id(event.path)
                
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

    def _handle_command(self, event: CommandEvent) -> None:
        if event.command == Command.SET_CONFIG:
            payload = event.payload or {}
            if "model" in payload and "pic_dir" in payload["model"]:
                new_pic_dir = payload["model"]["pic_dir"]
                logger.info(f"Configuration changed: pic_dir updated to {new_pic_dir}")
                
                # 1. Update MediaMonitorService directories
                # We need to stop it, update directories, and restart it
                self.media_monitor_service.stop()
                
                # Expand user path if necessary
                expanded_dir = os.path.expanduser(new_pic_dir)
                self.media_monitor_service.directories = [expanded_dir]
                
                # 2. Trigger a differential sync to index new files
                self.media_monitor_service.perform_differential_sync()
                
                # 3. Restart the monitor
                self.media_monitor_service.start()
                
                # 4. Purge missing files from the database
                purged_count = self.media_repository.purge_missing_files()
                logger.info(f"Purged {purged_count} missing files from the database.")
