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
from picframe.infrastructure.os.hal_factory import HALFactory
from picframe.api.app import create_app
from picframe.api.server import WebServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_picframe(base_dir: str, port: int = 9000, config_db_path: str | None = None, media_db_path: str | None = None) -> None:
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

    # 5. Initialize Renderer
    # TODO: Load config from config_repo
    renderer_config: dict[str, Any] = {
        "blur_amount": 12,
        "blur_zoom": 1.0,
        "blur_edges": False,
        "edge_alpha": 0.5,
        "fps": 20.0,
        "background": (0.2, 0.2, 0.2, 1.0),
        "font_file": "src/picframe/data/fonts/NotoSans-Regular.ttf",
        "shader": "src/picframe/data/shaders/blend_new",
        "use_sdl2": True,
    }
    renderer = Pi3dRenderer(renderer_config)

    # 6. Initialize Engine
    engine_config: dict[str, float] = {
        "time_delay": 10.0,
    }
    engine = PlaybackEngine(
        event_bus, event_bus, playlist_manager, renderer, engine_config
    )

    # 7. Initialize Web Server
    app = create_app()
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
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 9. Start Components
    logger.info("Starting Event Bus...")
    event_bus.start()

    logger.info("Starting Web Server...")
    web_server.start()

    logger.info("Starting Playback Engine...")
    # engine.start() blocks until stopped
    try:
        engine.start()
    except Exception as e:
        logger.error(f"Engine crashed: {e}")
    finally:
        logger.info("Cleaning up...")
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

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the picframe application")
    run_parser.add_argument("--dir", default=os.environ.get("PICFRAME_DIR", "~/.picframe"), help="Base directory for picframe data (default: ~/.picframe or PICFRAME_DIR env var)")
    run_parser.add_argument("--port", type=int, default=int(os.environ.get("PICFRAME_PORT", 9000)), help="Port for the web server (default: 9000 or PICFRAME_PORT env var)")
    run_parser.add_argument("--config-db", default=os.environ.get("PICFRAME_CONFIG_DB"), help="Path to config database (default: <dir>/data/config.db3 or PICFRAME_CONFIG_DB env var)")
    run_parser.add_argument("--media-db", default=os.environ.get("PICFRAME_MEDIA_DB"), help="Path to media database (default: <dir>/data/media_cache.db3 or PICFRAME_MEDIA_DB env var)")

    args = parser.parse_args()

    if args.command == "init":
        bootstrapper = EnvironmentBootstrapper(base_dir=args.dir, config_db_path=args.config_db, media_db_path=args.media_db)
        bootstrapper.bootstrap()
    elif args.command == "run":
        run_picframe(base_dir=args.dir, port=args.port, config_db_path=args.config_db, media_db_path=args.media_db)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

