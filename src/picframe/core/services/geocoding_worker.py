"""
Geocoding Worker Service.

This module provides a background worker thread that consumes a queue of
GPS coordinates and performs reverse geocoding lookups via the Nominatim API.
It respects strict rate limits and caches the results in the media repository.
"""

import logging
import threading
import time
from typing import Any

from picframe.core.repositories.interfaces import IConfigRepository, IMediaRepository
from picframe.geo_reverse import GeoReverse

logger = logging.getLogger(__name__)


class GeocodingWorker:
    """
    Background worker for rate-limited reverse geocoding.
    """

    def __init__(
        self,
        media_repository: IMediaRepository,
        config_repository: IConfigRepository,
        event_publisher: Any | None = None,
    ) -> None:
        """
        Initialize the GeocodingWorker.

        Args:
            media_repository: The repository to cache resolved locations.
            config_repository: The repository to fetch geocoding configuration.
            event_publisher: Optional event publisher to notify when locations are resolved.
        """
        self._media_repo = media_repository
        self._config_repo = config_repository
        self._event_publisher = event_publisher
        self._thread: threading.Thread | None = None
        self._is_running = False
        self._geo_reverse: GeoReverse | None = None
        self._last_config_check = 0.0

    def _init_geo_reverse(self) -> None:
        """Initialize or re-initialize the GeoReverse instance based on config."""
        load_geoloc = self._config_repo.get_app_config_bool("model.load_geoloc", False)
        geo_key = str(self._config_repo.get_app_config("model.geo_key", "this_needs_to@be_changed"))
        locale_value = str(self._config_repo.get_app_config("model.locale", "en_US.utf8"))
        key_list = self._config_repo.get_app_config("model.key_list", [
            ['tourism', 'amenity', 'isolated_dwelling'],
            ['suburb', 'village'],
            ['city', 'county'],
            ['region', 'state', 'province'],
            ['country']
        ])
        
        if load_geoloc and geo_key != "this_needs_to@be_changed":
            self._geo_reverse = GeoReverse(  # type: ignore[no-untyped-call]
                load_geoloc=True,
                geo_key=geo_key,
                key_list=key_list,
                language=self._language_from_locale(locale_value),
            )
        else:
            self._geo_reverse = None

    @staticmethod
    def _language_from_locale(locale_value: str) -> str:
        language = (locale_value or "").split(".", 1)[0].split("_", 1)[0].strip()
        if not language or language.upper() in {"C", "POSIX"}:
            return "en"
        return language

    def start(self) -> None:
        """Start the background worker thread."""
        if self._is_running:
            return

        self._is_running = True
        self._init_geo_reverse()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="GeocodingWorker")
        self._thread.start()
        logger.info("GeocodingWorker started.")

    def stop(self) -> None:
        """Stop the background worker thread."""
        if not self._is_running:
            return

        self._is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("GeocodingWorker stopped.")

    def queue_lookup(self, latitude: float, longitude: float) -> None:
        """
        Add a coordinate pair to the queue for reverse geocoding.

        Args:
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.
        """
        if not self._is_running:
            return
            
        # Check if we already have it cached before queuing
        cached = self._media_repo.get_location(latitude, longitude)
        if cached is None:
            self._media_repo.enqueue_location_lookup(latitude, longitude)

    def _worker_loop(self) -> None:
        """The main loop for the background worker thread."""
        while self._is_running:
            try:
                # Periodically check for config changes (every 60 seconds)
                current_time = time.time()
                if current_time - self._last_config_check > 60.0:
                    self._init_geo_reverse()
                    self._last_config_check = current_time

                # If geocoding is disabled, sleep and continue
                if not self._geo_reverse:
                    time.sleep(1.0)
                    continue

                # Wait for an item in the queue
                task = self._media_repo.dequeue_location_lookup()
                if not task:
                    time.sleep(1.0)
                    continue

                lat, lon = task

                if not self._is_running:
                    break

                # Double check cache in case it was resolved while waiting in queue
                cached = self._media_repo.get_location(lat, lon)
                if cached is not None:
                    continue

                # Perform the lookup
                logger.debug(f"GeocodingWorker: Looking up {lat}, {lon}")
                address = self._geo_reverse.get_address(lat, lon)  # type: ignore[no-untyped-call]
                
                if address:
                    self._media_repo.save_location(lat, lon, address)
                    logger.debug(f"GeocodingWorker: Resolved {lat}, {lon} to '{address}'")
                    
                    # Publish an event to notify the system that a location was resolved
                    # This allows the UI to update if it's currently displaying this media
                    if hasattr(self, '_event_publisher') and self._event_publisher:
                        from picframe.core.events.dto import CommandEvent, Command
                        self._event_publisher.publish(CommandEvent(command=Command.REQUEST_STATE))
                else:
                    logger.warning(f"GeocodingWorker: Failed to resolve {lat}, {lon}")

            except Exception as e:
                logger.error(f"GeocodingWorker error: {e}", exc_info=True)
                # Sleep briefly on error to prevent tight loop
                time.sleep(5.0)
