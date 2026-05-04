"""
FastAPI Application Setup.

This module initializes the FastAPI application, configures CORS,
and sets up the necessary dependencies for the web control plane.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from picframe.api.models import AppConfig
from picframe.core.events.dto import Command, CommandEvent, CurrentMediaChangedEvent, StateEvent
from picframe.core.events.interfaces import IEventPublisher, IEventSubscriber
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)


def create_app(
    event_publisher: IEventPublisher | None = None,
    event_subscriber: IEventSubscriber | None = None,
    cors_allowed_origins: list[str] | None = None,
    config_repository: IConfigRepository | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Args:
        event_publisher: Optional event publisher for sending commands.
        event_subscriber: Optional event subscriber for receiving state updates.
        cors_allowed_origins: Optional list of allowed origins for CORS. Defaults to ["*"].

    Returns:
        FastAPI: The configured application instance.
    """
    logger.info("Initializing FastAPI application...")
    
    app = FastAPI(
        title="Picframe Web Control Plane",
        description="API for controlling the Picframe digital picture frame.",
        version="2.0.0",
    )

    # Configure CORS
    if cors_allowed_origins is None:
        cors_allowed_origins = ["*"]
        
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Basic health check endpoint."""
        return {"status": "ok"}

    @app.websocket("/ws/state")
    async def websocket_state(websocket: WebSocket) -> None:
        """WebSocket endpoint for state synchronization."""
        await websocket.accept()
        
        # Queue for sending messages to the websocket from the event bus
        send_queue: asyncio.Queue[str] = asyncio.Queue()
        
        # Capture the event loop here, in the main thread
        loop = asyncio.get_running_loop()
        
        def handle_media_changed(event: CurrentMediaChangedEvent) -> None:
            media_dict: dict[str, Any] = {}
            if hasattr(event.media_item, "to_dict") and callable(event.media_item.to_dict):
                media_dict = cast(dict[str, Any], event.media_item.to_dict())
            elif hasattr(event.media_item, "__dict__"):
                media_dict = cast(dict[str, Any], event.media_item.__dict__)
            elif isinstance(event.media_item, dict):
                media_dict = cast(dict[str, Any], event.media_item)
            else:
                media_dict = {"raw": str(event.media_item)}
                
            # Add a URL for the frontend to fetch the image
            if "filepath" in media_dict and media_dict["filepath"]:
                # We'll serve media from a new /media endpoint
                media_dict["file_path"] = f"/media?path={media_dict['filepath']}"
            elif "file_path" not in media_dict:
                # Fallback for no_pictures.jpg or other cases where filepath isn't set
                media_dict["file_path"] = "/media?path=no_pictures.jpg"
                
            # Map backend fields to frontend expected fields
            if "latitude" in media_dict and "longitude" in media_dict:
                if media_dict["latitude"] is not None and media_dict["longitude"] is not None:
                    media_dict["location"] = {
                        "lat": media_dict["latitude"],
                        "lon": media_dict["longitude"]
                    }
            
            # Group EXIF data
            exif_keys = [
                "make", "model", "lens", "f_number", "exposure_time", "iso",
                "focal_length", "exif_datetime", "caption", "tags", "location"
            ]
            exif_data = {}
            for key in exif_keys:
                if key in media_dict and media_dict[key] is not None:
                    # Don't overwrite the location object we just created
                    if key == "location" and isinstance(media_dict[key], dict):
                        continue
                    exif_data[key] = media_dict[key]
            
            if exif_data:
                media_dict["exif"] = exif_data
                
            msg = json.dumps({"type": "MediaChangedEvent", "media": media_dict})
            # Use call_soon_threadsafe because this callback runs in the event bus thread
            loop.call_soon_threadsafe(send_queue.put_nowait, msg)

        def handle_state_changed(event: StateEvent) -> None:
            msg = json.dumps({"type": "StateEvent", "state": event.state.name})
            loop.call_soon_threadsafe(send_queue.put_nowait, msg)

        if event_subscriber:
            event_subscriber.subscribe(CurrentMediaChangedEvent, handle_media_changed)
            event_subscriber.subscribe(StateEvent, handle_state_changed)

        async def receive_messages() -> None:
            try:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Received websocket message: {data}")
                    try:
                        payload = json.loads(data)
                        command_str = payload.get("command")
                        if command_str and event_publisher:
                            if command_str == "NEXT":
                                event_publisher.publish(CommandEvent(command=Command.NEXT))
                            elif command_str == "PREV":
                                event_publisher.publish(CommandEvent(command=Command.PREV))
                            elif command_str == "PAUSE":
                                event_publisher.publish(CommandEvent(command=Command.PAUSE))
                            elif command_str == "PLAY":
                                event_publisher.publish(CommandEvent(command=Command.PLAY))
                            elif command_str == "SET_BRIGHTNESS":
                                value = payload.get("value")
                                if value is not None:
                                    event_publisher.publish(
                                        CommandEvent(
                                            command=Command.SET_BRIGHTNESS, payload=float(value)
                                        )
                                    )
                            elif command_str == "DISPLAY_ON":
                                event_publisher.publish(CommandEvent(command=Command.DISPLAY_ON))
                            elif command_str == "DISPLAY_OFF":
                                event_publisher.publish(CommandEvent(command=Command.DISPLAY_OFF))
                            elif command_str == "DELETE":
                                event_publisher.publish(CommandEvent(command=Command.DELETE))
                            elif command_str == "PURGE_FILES":
                                event_publisher.publish(CommandEvent(command=Command.PURGE_FILES))
                            elif command_str == "STOP":
                                event_publisher.publish(CommandEvent(command=Command.STOP))
                            elif command_str == "REBOOT_HOST":
                                event_publisher.publish(CommandEvent(command=Command.REBOOT_HOST))
                            elif command_str == "SHUTDOWN_HOST":
                                event_publisher.publish(CommandEvent(command=Command.SHUTDOWN_HOST))
                            elif command_str == "SET_CONFIG":
                                # The frontend sends the payload directly in the root object,
                                # not nested under "payload"
                                # e.g. {"command": "SET_CONFIG", "viewer": {"show_clock": true}}
                                config_payload = payload.get("payload")
                                if config_payload is None:
                                    # Extract everything except the command key
                                    config_payload = {
                                        k: v for k, v in payload.items() if k != "command"
                                    }
                                
                                if config_payload:
                                    event_publisher.publish(
                                        CommandEvent(
                                            command=Command.SET_CONFIG, payload=config_payload
                                        )
                                    )
                    except json.JSONDecodeError:
                        logger.error("Invalid JSON received on websocket")
            except WebSocketDisconnect:
                pass

        async def send_messages() -> None:
            try:
                while True:
                    msg = await send_queue.get()
                    await websocket.send_text(msg)
            except WebSocketDisconnect:
                pass

        try:
            # Run both tasks concurrently
            await asyncio.gather(
                receive_messages(),
                send_messages(),
            )
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            if event_subscriber:
                event_subscriber.unsubscribe(CurrentMediaChangedEvent, handle_media_changed)
                event_subscriber.unsubscribe(StateEvent, handle_state_changed)

    @app.post("/api/system/reboot")
    async def api_reboot() -> dict[str, str]:
        """Trigger a full host-level OS reboot."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.REBOOT_HOST))
        return {"status": "rebooting"}

    @app.post("/api/system/shutdown")
    async def api_shutdown() -> dict[str, str]:
        """Trigger a full host-level OS shutdown."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.SHUTDOWN_HOST))
        return {"status": "shutting down"}

    @app.post("/api/maintenance/purge-db")
    async def api_purge_db() -> dict[str, str]:
        """Trigger a database purge of missing files."""
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.PURGE_FILES))
        return {"status": "purging database"}

    @app.get("/api/config")
    async def api_get_config() -> dict[str, Any]:
        """Get the full application configuration."""
        if not config_repository:
            return {}
            
        # Use ConfigService to handle the unflattening logic
        # We create a temporary instance here since the API layer doesn't have
        # direct access to the long-running ConfigService instance.
        # In a more complex setup, this would be injected.
        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass
            
        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
        nested_config = temp_service.get_nested_config()
        
        # Pass through Pydantic model to populate default values
        from picframe.api.models import AppConfig
        app_config = AppConfig(**nested_config)
        return app_config.model_dump()

    @app.put("/api/config")
    async def api_put_config(payload: AppConfig = Body(...)) -> dict[str, str]:
        """Update the application configuration."""
        if not config_repository:
            return {"status": "error", "message": "Config repository not available"}
            
        # Use ConfigService to handle the flattening logic
        class DummyPublisher(IEventPublisher):
            def publish(self, event: Any) -> None: pass
        class DummySubscriber(IEventSubscriber):
            def subscribe(self, event_type: type, callback: Any) -> None: pass
            def unsubscribe(self, event_type: type, callback: Any) -> None: pass
            
        from picframe.core.services.config_service import ConfigService
        temp_service = ConfigService(config_repository, DummySubscriber(), DummyPublisher())
        
        # Convert Pydantic model to dict, excluding unset values to avoid overwriting
        # existing config with None values if the frontend didn't send them.
        config_dict = payload.model_dump(exclude_unset=True)
        temp_service.update_nested_config(config_dict)
                
        # Publish a SET_CONFIG event to notify other components
        if event_publisher:
            event_publisher.publish(CommandEvent(command=Command.SET_CONFIG, payload=config_dict))
            
        return {"status": "success"}

    @app.get("/media")
    async def serve_media(path: str) -> FileResponse:
        """Serve media files from the filesystem."""
        file_path = Path(path).resolve()
        
        # Basic security check: only serve files with known media extensions
        # to prevent arbitrary file read (e.g., /etc/passwd)
        allowed_extensions = {
            ".jpg", ".jpeg", ".png", ".gif", ".heic",
            ".mp4", ".mov", ".mkv", ".avi", ".webm"
        }
        
        if (file_path.exists() and file_path.is_file() and
            file_path.suffix.lower() in allowed_extensions):
            return FileResponse(file_path)
            
        # Return a 404 or a default image if not found
        # First try the user's configuration directory
        user_no_pic_path = Path.home() / ".picframe" / "data" / "no_pictures.jpg"
        if user_no_pic_path.exists() and user_no_pic_path.is_file():
            return FileResponse(user_no_pic_path)
            
        # Fallback to the source code directory
        return FileResponse(Path(__file__).parent.parent / "data" / "no_pictures.jpg")

    # Serve SPA static files
    html_dir = Path(__file__).parent.parent / "html"
    if html_dir.exists():
        # Mount the assets directory
        assets_dir = html_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # Catch-all route for SPA
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            requested_file = html_dir / full_path
            if full_path and requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(html_dir / "index.html")
    else:
        logger.warning(
            f"Frontend build directory not found at {html_dir}. Web UI will not be available."
        )

    return app
