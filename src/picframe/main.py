import logging
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
from picframe.infrastructure.os.hal_factory import HALFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """
    Composition Root for Picframe.
    Initializes and wires all components together.
    """
    logger.info("Starting Picframe...")

    # 1. Initialize Repositories
    # TODO: Use actual paths from environment or arguments
    config_db_path = "config.db3"
    media_db_path = "media_cache.db3"
    
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
        event_bus, playlist_manager, renderer, engine_config
    )

    # 7. Setup Graceful Shutdown
    shutdown_event = threading.Event()

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info("Received shutdown signal. Stopping...")
        shutdown_event.set()
        engine.stop()
        event_bus.stop()
        # Keep a reference to display_power_manager to prevent garbage collection
        # and allow it to handle events until the bus stops.
        _ = display_power_manager
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 8. Start Components
    logger.info("Starting Event Bus...")
    event_bus.start()

    logger.info("Starting Playback Engine...")
    # engine.start() blocks until stopped
    try:
        engine.start()
    except Exception as e:
        logger.error(f"Engine crashed: {e}")
    finally:
        logger.info("Cleaning up...")
        engine.stop()
        event_bus.stop()
        logger.info("Picframe stopped.")


if __name__ == "__main__":
    main()
