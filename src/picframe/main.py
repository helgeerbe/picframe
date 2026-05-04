"""
Main entry point for the Picframe application.

This module provides the CLI interface (`picframe init` and `picframe run`)
and acts as the Composition Root, wiring together all the core components,
services, and infrastructure adapters required to run the digital picture frame.
"""

import argparse
import logging
import os
import signal
import sys
import threading
from typing import Any

from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.bus import PriorityQueueEventBus
from picframe.core.renderers.pi3d_renderer import Pi3dRenderer
from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
from picframe.core.repositories.sqlite_media import SQLiteMediaRepository
from picframe.core.services.playlist import PlaylistManager
from picframe.core.services.bootstrapper import EnvironmentBootstrapper
from picframe.core.services.config_service import ConfigService
from picframe.core.services.media_monitor import MediaMonitorService
from picframe.core.services.image_processing import ImageProcessingService
from picframe.infrastructure.os.hal_factory import HALFactory
from picframe.api.app import create_app
from picframe.api.server import WebServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_picframe(base_dir: str, port: int = 9000, config_db_path: str | None = None, media_db_path: str | None = None, html_dir: str | None = None) -> None:
    """
    Composition Root for Picframe.
    Initializes and wires all components together.
    """
    logger.info(f"Starting Picframe (Web server port: {port})...")

    # 1. Initialize Repositories
    data_dir = os.path.join(os.path.expanduser(base_dir), "data")
    config_db_path = config_db_path or os.path.join(data_dir, "config.db3")
    media_db_path = media_db_path or os.path.join(data_dir, "media_cache.db3")
    
    _config_repo = SQLiteConfigRepository(config_db_path)
    media_repo = SQLiteMediaRepository(media_db_path)

    # 2. Initialize Event Bus
    event_bus = PriorityQueueEventBus()

    # 3. Initialize Hardware Abstraction Layer (HAL)
    # TODO: Load display_hdmi from config_repo (Issue #630)
    display_output = "HDMI-A-1"
    hal_adapters = HALFactory.create_adapters(display_output=display_output)
    logger.info(f"HAL Adapters injected: {hal_adapters}")

    # 4. Initialize Services
    playlist_manager = PlaylistManager(media_repo)
    from picframe.core.services.display_power import DisplayPowerManager
    display_power_manager = DisplayPowerManager(event_bus, hal_adapters.display_power)
    from picframe.core.services.system_manager import SystemManager
    system_manager = SystemManager(event_bus, hal_adapters.system_manager)
    config_service = ConfigService(_config_repo, event_bus, event_bus)
    
    # Initialize ImageProcessingService
    image_processing_service = ImageProcessingService(cache_dir=os.path.join(data_dir, "cache"))
    
    # Initialize MediaMonitorService
    nested_config = config_service.get_nested_config()
    model_config = nested_config.get("model", {})
    
    pic_dir = model_config.get("pic_dir", os.path.join(data_dir, "media"))
    # Expand user path (e.g., ~)
    pic_dir = os.path.expanduser(pic_dir)
    media_directories = [pic_dir]
    
    logger.info(f"Configured media directories: {media_directories}")
    
    allowed_extensions = set(model_config.get("allowed_extensions", [
        ".jpg", ".jpeg", ".png", ".heic", ".heif",
        ".mp4", ".mkv", ".flv", ".mov", ".avi", ".webm", ".hevc"
    ]))
    follow_links = model_config.get("follow_links", False)
    
    media_monitor_service = MediaMonitorService(
        publisher=event_bus,
        directories=media_directories,
        allowed_extensions=allowed_extensions,
        follow_links=follow_links
    )

    from picframe.core.services.media_indexer import MediaIndexerService
    media_indexer_service = MediaIndexerService(
        event_subscriber=event_bus,
        media_repository=media_repo,
        config_repository=_config_repo,
        image_processing_service=image_processing_service,
        media_monitor_service=media_monitor_service
    )

    # 5. Initialize Renderer
    renderer_config = nested_config.get("viewer", {})
    renderer = Pi3dRenderer(renderer_config, event_subscriber=event_bus, config_repository=_config_repo)

    # 6. Initialize Engine
    engine = PlaybackEngine(
        event_bus, event_bus, playlist_manager, renderer, model_config
    )

    # 7. Initialize Web Server
    cors_origins = _config_repo.get_app_config("cors_allowed_origins", ["*"])
    app = create_app(
        event_publisher=event_bus,
        event_subscriber=event_bus,
        cors_allowed_origins=cors_origins,
        config_repository=_config_repo,
        html_dir=html_dir or os.path.join(base_dir, "html"),
    )
    web_server = WebServer(app, port=port)

    # 8. Setup Graceful Shutdown
    shutdown_event = threading.Event()

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info("Received shutdown signal. Stopping...")
        shutdown_event.set()
        web_server.stop()
        engine.stop()
        event_bus.stop()
        # Keep a reference to display_power_manager to prevent garbage collection
        # and allow it to handle events until the bus stops.
        _ = display_power_manager
        _ = system_manager
        _ = config_service
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 9. Start Components
    logger.info("Starting Event Bus...")
    event_bus.start()

    logger.info("Starting Web Server...")
    web_server.start()
    
    logger.info("Starting Media Monitor Service...")
    media_monitor_service.perform_differential_sync()
    media_monitor_service.start()

    logger.info("Starting Playback Engine...")
    # engine.start() blocks until stopped
    try:
        engine.start()
    except Exception as e:
        logger.error(f"Engine crashed: {e}")
    finally:
        logger.info("Cleaning up...")
        media_monitor_service.stop()
        image_processing_service.shutdown()
        web_server.stop()
        engine.stop()
        event_bus.stop()
        logger.info("Picframe stopped.")


def main() -> None:
    """
    Main entry point for the picframe CLI.

    Parses command-line arguments and executes the corresponding command.
    Available commands:
        - init: Initializes the picframe environment (directories, assets, databases).
        - run: Starts the main picframe application.
    """
    parser = argparse.ArgumentParser(description="Picframe - Digital Picture Frame")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize the picframe environment")
    init_parser.add_argument("--dir", default=os.environ.get("PICFRAME_DIR", "~/.picframe"), help="Base directory for picframe data (default: ~/.picframe or PICFRAME_DIR env var)")
    init_parser.add_argument("--config-db", default=os.environ.get("PICFRAME_CONFIG_DB"), help="Path to config database (default: <dir>/data/config.db3 or PICFRAME_CONFIG_DB env var)")
    init_parser.add_argument("--media-db", default=os.environ.get("PICFRAME_MEDIA_DB"), help="Path to media database (default: <dir>/data/media_cache.db3 or PICFRAME_MEDIA_DB env var)")
    init_parser.add_argument("-f", "--force", action="store_true", help="Force initialization without prompting (overwrites existing databases if specified)")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the picframe application")
    run_parser.add_argument("--dir", default=os.environ.get("PICFRAME_DIR", "~/.picframe"), help="Base directory for picframe data (default: ~/.picframe or PICFRAME_DIR env var)")
    run_parser.add_argument("--port", type=int, default=int(os.environ.get("PICFRAME_PORT", 9000)), help="Port for the web server (default: 9000 or PICFRAME_PORT env var)")
    run_parser.add_argument("--config-db", default=os.environ.get("PICFRAME_CONFIG_DB"), help="Path to config database (default: <dir>/data/config.db3 or PICFRAME_CONFIG_DB env var)")
    run_parser.add_argument("--media-db", default=os.environ.get("PICFRAME_MEDIA_DB"), help="Path to media database (default: <dir>/data/media_cache.db3 or PICFRAME_MEDIA_DB env var)")
    run_parser.add_argument("--html-dir", default=os.environ.get("PICFRAME_HTML_DIR"), help="Path to frontend HTML assets (default: <dir>/html or PICFRAME_HTML_DIR env var)")

    args = parser.parse_args()

    if args.command == "init":
        bootstrapper = EnvironmentBootstrapper(base_dir=args.dir, config_db_path=args.config_db, media_db_path=args.media_db, force=args.force)
        bootstrapper.bootstrap()
    elif args.command == "run":
        run_picframe(base_dir=args.dir, port=args.port, config_db_path=args.config_db, media_db_path=args.media_db, html_dir=args.html_dir)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

