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

from picframe.api.app import create_app
from picframe.api.server import WebServer
from picframe.core.engine.playback import PlaybackEngine
from picframe.core.events.bus import PriorityQueueEventBus
from picframe.core.renderers.pi3d_renderer import Pi3dRenderer
from picframe.core.repositories.sqlite_config import SQLiteConfigRepository
from picframe.core.repositories.sqlite_media import SQLiteMediaRepository
from picframe.core.services.bootstrapper import EnvironmentBootstrapper
from picframe.core.services.config_service import ConfigService
from picframe.core.services.image_processing import ImageProcessingService
from picframe.core.services.media_monitor import MediaMonitorService
from picframe.core.services.playlist import PlaylistManager
from picframe.infrastructure.os.hal_factory import HALFactory

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

    # 3. Initialize Config Service (Needed for HAL)
    config_service = ConfigService(_config_repo, event_bus, event_bus)
    nested_config = config_service.get_nested_config()

    # 4. Initialize Hardware Abstraction Layer (HAL)
    display_output = str(_config_repo.get_app_config("viewer.display_hdmi", "HDMI-A-1"))
    hardware_input_config = nested_config.get("hardware_inputs", {})
    hal_adapters = HALFactory.create_adapters(
        display_output=display_output,
        hardware_input_config=hardware_input_config,
        publisher=event_bus
    )
    logger.info(f"HAL Adapters injected: {hal_adapters}")

    # 5. Initialize Services
    playlist_manager = PlaylistManager(media_repo, _config_repo, event_bus)
    from picframe.core.services.display_power import DisplayPowerManager
    display_power_manager = DisplayPowerManager(event_bus, hal_adapters.display_power)
    from picframe.core.services.system_manager import SystemManager
    system_manager = SystemManager(event_bus, hal_adapters.system_manager)
    
    # Initialize ImageProcessingService
    cache_dir = os.path.join(data_dir, "cache")
    image_processing_service = ImageProcessingService(cache_dir=cache_dir)
    
    # Initialize MediaMonitorService
    model_config = nested_config.get("model", {})
    
    pic_dir = model_config.get("pic_dir", os.path.join(data_dir, "media"))
    # Expand user path (e.g., ~)
    pic_dir = os.path.expanduser(pic_dir)
    media_directories = [pic_dir]
    
    logger.info(f"Configured media directories: {media_directories}")
    
    image_extensions = model_config.get("image_extensions", [
        ".jpg", ".jpeg", ".png", ".heic", ".heif"
    ])
    video_extensions = model_config.get("video_extensions", [
        ".mp4", ".mkv", ".flv", ".mov", ".avi", ".webm", ".hevc"
    ])
    allowed_extensions = set(image_extensions + video_extensions)
    follow_links = model_config.get("follow_links", False)
    
    media_monitor_service = MediaMonitorService(
        publisher=event_bus,
        directories=media_directories,
        allowed_extensions=allowed_extensions,
        follow_links=follow_links
    )

    from picframe.core.metadata.image_strategy import ImageMetadataStrategy
    from picframe.core.metadata.video_strategy import VideoMetadataStrategy
    from picframe.core.services.media_indexer import MediaIndexerService
    
    display_w_val = _config_repo.get_app_config("viewer.display_w", 0)
    display_w = int(display_w_val) if display_w_val else 0
    display_h_val = _config_repo.get_app_config("viewer.display_h", 0)
    display_h = int(display_h_val) if display_h_val else 0
    
    media_indexer_service = MediaIndexerService(
        event_subscriber=event_bus,
        media_repository=media_repo,
        config_repository=_config_repo,
        image_processing_service=image_processing_service,
        media_monitor_service=media_monitor_service,
        image_strategy=ImageMetadataStrategy(),
        video_strategy=VideoMetadataStrategy(
            display_w=display_w,
            display_h=display_h,
            config_repository=_config_repo,
            cache_dir=cache_dir,
        )
    )

    # 5. Initialize Renderer
    from picframe.core.events.dto import RendererConfig
    renderer_config = RendererConfig(
        display_x=int(_config_repo.get_app_config("viewer.display_x", 0)),
        display_y=int(_config_repo.get_app_config("viewer.display_y", 0)),
        display_w=int(_config_repo.get_app_config("viewer.display_w")) if _config_repo.get_app_config("viewer.display_w") not in (None, "") else None,
        display_h=int(_config_repo.get_app_config("viewer.display_h")) if _config_repo.get_app_config("viewer.display_h") not in (None, "") else None,
        fps=int(_config_repo.get_app_config("viewer.fps", 20)),
        background=tuple(_config_repo.get_app_config("viewer.background", [0.0, 0.0, 0.0, 1.0])), # type: ignore
        use_glx=_config_repo.get_app_config_bool("viewer.use_glx", False),
        use_sdl2=_config_repo.get_app_config_bool("viewer.use_sdl2", False),
        shader_path=str(_config_repo.get_app_config("viewer.shader", "blend_new")),
        kenburns=_config_repo.get_app_config_bool("viewer.kenburns", False),
        show_clock=_config_repo.get_app_config_bool("viewer.show_clock", False),
        clock_format=str(_config_repo.get_app_config("viewer.clock_format", "%H:%M")),
        show_text_enabled=_config_repo.get_app_config_bool("viewer.show_text_enabled", False),
        text_overlay_format=str(_config_repo.get_app_config("viewer.text_overlay_format", "%b %d, %Y")),
        time_fade=float(_config_repo.get_app_config("model.fade_time", 2.0)),
        time_delay=float(_config_repo.get_app_config("model.time_delay", 200.0)),
        show_text_tm=float(_config_repo.get_app_config("viewer.show_text_tm", 10.0)),
        font_file=str(_config_repo.get_app_config("viewer.font_file", "")),
        blend_type=str(_config_repo.get_app_config("viewer.blend_type", "blend")),
        edge_alpha=float(_config_repo.get_app_config("viewer.edge_alpha", 0.5)),
        fit=_config_repo.get_app_config_bool("viewer.fit", False),
        video_extensions=_config_repo.get_app_config("model.video_extensions", [".mp4", ".mov", ".avi", ".mkv"]),
    )
    renderer = Pi3dRenderer(renderer_config, event_subscriber=event_bus, event_publisher=event_bus)
    
    from picframe.core.renderers.gst_video_renderer import GstVideoRenderer
    max_software_decode_resolution = str(_config_repo.get_app_config("viewer.max_software_decode_resolution", "1280x720"))
    video_player = GstVideoRenderer(event_publisher=event_bus, max_software_decode_resolution=max_software_decode_resolution)

    # 6. Initialize Engine
    engine = PlaybackEngine(
        event_bus,
        event_bus,
        playlist_manager,
        renderer,
        model_config,
        config_repository=_config_repo,
        video_player=video_player,
        cache_dir=cache_dir,
    )

    # 7. Initialize Web Server
    http_config = nested_config.get("http", {})
    cors_origins = http_config.get("cors_allowed_origins", ["*"])
    app = create_app(
        event_publisher=event_bus,
        event_subscriber=event_bus,
        cors_allowed_origins=cors_origins,
        config_repository=_config_repo,
        media_repository=media_repo,
        image_processing_service=image_processing_service,
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
        media_indexer_service.stop()
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
        logger.critical(f"Fatal error in main thread: {e}", exc_info=True)
        from picframe.core.events.dto import SystemErrorEvent
        event_bus.publish(SystemErrorEvent(message=f"Fatal Error: {e}", component="MainThread"))
        # Give the event bus a moment to broadcast the error before shutting down
        import time
        time.sleep(1.0)
    finally:
        logger.info("Cleaning up...")
        media_indexer_service.stop()
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
